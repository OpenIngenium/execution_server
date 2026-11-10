import tornado.httpserver
import tornado.autoreload
from tornado.web import RequestHandler
from tornado.escape import json_decode
from tornado import gen

from concurrent.futures import ProcessPoolExecutor
from multiprocessing import current_process
from concurrent.futures.process import BrokenProcessPool

from functools import wraps
import jwt
import json
import copy
import time
import psutil
import datetime
import os
import signal

import ast
import traceback

from configparser import ConfigParser

from state_manager import StateManager

import logging
from collections import OrderedDict

import importlib

from ingenium_embedded import ingenium_config as ic
from ingenium_embedded import ingenium_library
from ingenium_embedded.ingenium_library import get_now_utc, EventName, ErrorType, ErrorSource, dict_digest, \
    update_execution, handle_execution_error, \
    get_execution, get_execution_step, get_simple_elements, get_element, compute_step, \
    report_step_results, report_step_results2, \
    create_new_run, import_procedure_section, call_procedure_section, suspend_resume_execution, \
    wait_execution_switch, switch_execution, post_execution_message, refresh_venue_tokens

# Note: json_logging is initialized by ingenium_config
logger = logging.getLogger('Global')
consoleHandler = logging.StreamHandler()
logger.addHandler(consoleHandler)
logger.propagate = False

exec_venue_private_pem = os.environ.get('EXEC_VENUE_PRIVATE_PEM', '')
exec_venue_public_pem = os.environ.get('EXEC_VENUE_PUBLIC_PEM', '')
public_pem = os.environ.get('PUBLIC_PEM', '')


jwt_options = {
    'verify_signature': True,
    'verify_exp': True,
    'verify_nbf': False,
    'verify_iat': True,
    'verify_aud': False
}

def get_pid():
    pid = current_process().pid
    return pid

def run_step(step):

    # To keep token valid during automatic execution
    refresh_venue_tokens()

    execution_id = step.get('execution_id', '')
    number = step.get('number', '')    
    elem_id = step.get('elem_id', '')

    code_name = ''
    if ('code' in step) and ('name' in step['code']):
        code_name = step['code']['name']
    segments = code_name.split('.')

    if len(segments) != 2:
        raise Exception(f'code name is not in expected format. code_name: {code_name}')

    module_name = segments[0]
    function_name = segments[1]

    full_module_name = f'ingenium_embedded.{module_name}'

    step_module = importlib.import_module(full_module_name)
    function_to_call = getattr(step_module, function_name)
    return function_to_call(step)

def run_execution(step, execution_id, elem_id, user_name, run_mode):
    # Set this as soon as running the execution in a worker
    # so that JSON style logging can use the correct user name
    ic.username = user_name
    logger.info(f'run_execution step is None: {step is None} execution_id: {execution_id} elem_id: {elem_id} user_name: {user_name} run_mode: {run_mode}')
    
    ingenium_library.reload_execution_cache(execution_id)
    
    if run_mode == 'SYNC':
        if step is None:
            # Use for tests of core server
            step, error_msg = get_execution_step(execution_id, elem_id)
            if error_msg is not None:
                handle_execution_error(execution_id, elem_id, error_msg)
                return

            if 'execution' not in step:            
                step['execution'] = {}
            if 'meta_data' not in step['execution']:
                step['execution']['meta_data'] = {}
            step['execution']['meta_data']['status'] = 'RUNNING'
            step['execution']['meta_data']['time_started'] = get_now_utc()
            step['execution']['meta_data']['test_conductor'] = user_name

            update_execution(execution_id, {'status': 'RUNNING'})

            ##
            executable = step.get('executable')
            # old style step may not have executable field. consider as EXECUTED
            if executable is None or executable == 'EXECUTED':
                step_out = run_step(step)
                step_out = report_step_results(step, step_out.get('execution'), None)
                update_execution(execution_id, {'status': 'IDLE'})
                return step_out
            elif executable == 'COMPUTED':
                step_out, error_msg = compute_step(execution_id, elem_id)
                update_execution(execution_id, {'status': 'IDLE'})
                if error_msg is None:
                    return step_out
                else:
                    logger.warning(error_msg)
                    return step
            else:
                return step
        else:
            # Used for tests of execution server
            execution_id = step.get('execution_id')

            if 'execution' not in step:            
                step['execution'] = {}
            if 'meta_data' not in step['execution']:
                step['execution']['meta_data'] = {}
            step['execution']['meta_data']['status'] = 'RUNNING'
            step['execution']['meta_data']['time_started'] = get_now_utc()
            step['execution']['meta_data']['test_conductor'] = user_name
            return run_step(step)
    
    # cache the original execution_id
    execution_id_0 = execution_id

    update_execution(execution_id, {'status': 'RUNNING'})

    execution, error_msg = get_execution(execution_id)
    if error_msg is not None:
        handle_execution_error(execution_id, elem_id, error_msg)
        return
    
    mode = execution.get('mode')
    logger.debug(f'run_execution execution_id: {execution_id} mode: {mode}')
    simple_elems, error_msg = get_simple_elements(execution_id)
    if error_msg is not None:
        stop_execution_with_error(execution_id, error_msg)
        return

    elems_count = len(simple_elems)

    # Find the location of the step
    step_idx = get_step_idx(simple_elems, elem_id)
    if step_idx == -1:
        logger.error(f'step not found. execution_id: {execution_id} elem_id: {elem_id}')
        return

    # consider as initial run if elem_id was specified. break point will be ignore for the elem.
    initial = True if elem_id else False
    idx, pause = get_next_step_idx(execution_id, execution, simple_elems, step_idx, initial)
    
    logger.debug(f'step_idx: {step_idx} idx: {idx} pause: {pause}')

    step_executed = False
    step_out = None
    while (not pause) and (idx > -1) and (idx < elems_count):
        elem = simple_elems[idx]
        elem_id = elem.get('elem_id')
        elem_type = elem.get('elem_type')
        number = elem.get('number')
        title = elem.get('title')
        executable = elem.get('executable')

        logger.info(f'checking element execution_id: {execution_id} number: {number} title: {title} idx: {idx} elem_id: {elem_id} elem_type: {elem_type}')
        update_execution(execution_id, {'current_step_id': elem_id, 'status': 'RUNNING'})

        error_msg = None
        current_step_id = ''
        step_status = 'NONE'

        step, error_msg = get_execution_step(execution_id, elem_id)
        if error_msg is not None:
            stop_execution_with_error(execution_id, error_msg)
            return

        if elem_type == 'PROCEDURE_SECTION':
            callable = step.get('execution_user_input', {}).get('callable')
            imported = step.get('imported')

            child_execution_id = step.get('child_execution_id')

            if child_execution_id:
                update_execution(execution_id, {'status': 'IDLE'})
                child_execution, error_msg = suspend_resume_execution(execution_id, child_execution_id)
                if error_msg is not None:
                    stop_execution_with_error(execution_id, error_msg)
                    return

                dummy, error_msg = switch_execution(execution_id, child_execution_id)
                if error_msg is not None:
                    stop_execution_with_error(execution_id, error_msg)
                    return

                execution = child_execution
                execution_id = execution.get('execution_id')

                try:
                    wait_execution_switch(execution_id)
                except:
                    logger.error(traceback.format_exc())
                    stop_execution_with_error(execution_id, 'Error while waiting for execution to switch')
                    return

                simple_elems, error_msg = get_simple_elements(execution_id)
                if error_msg is not None:
                    stop_execution_with_error(execution_id, error_msg)
                    return
                
                elems_count = len(simple_elems)
                idx = 0
                # reset idx to start from the first element of the child execution
                idx0 = 0
                idx, pause = get_next_step_idx(execution_id, execution, simple_elems, idx0, False)
                logger.debug(f'child execution execution_id: {execution_id} elems_count: {elems_count} idx0: {idx0} idx: {idx}')
                continue
            else:
                if imported:
                    if callable:
                        msg = f'procedure was called. but there was no child execution. number: {number}'
                        logger.error(msg)
                        stop_execution_with_error(execution_id, msg)
                        return
                    else:
                        # skip imported procedure section
                        idx0 = idx + 1
                        idx, pause = get_next_step_idx(execution_id, execution, simple_elems, idx0, False)
                        logger.debug(f'skip imported procedure section execution_id: {execution_id} elems_count: {elems_count} idx0: {idx0} idx: {idx}')
                        continue
                else:
                    if callable:
                        logger.debug(f'call procedure number: {number} elem_id: {elem_id}')
                        child_execution, error_msg = call_procedure_section(execution_id, elem_id)
                        if error_msg is not None:
                            stop_execution_with_error(execution_id, error_msg)
                            return

                        dummy, error_msg = switch_execution(execution_id, child_execution['execution_id'])
                        if error_msg is not None:
                            stop_execution_with_error(execution_id, error_msg)
                            return

                        execution = child_execution
                        execution_id = execution.get('execution_id')

                        try:
                            wait_execution_switch(execution_id)
                        except:
                            logger.error(traceback.format_exc())
                            stop_execution_with_error(execution_id, 'Error while waiting for execution to switch')
                            return

                        simple_elems, error_msg = get_simple_elements(execution_id)
                        if error_msg is not None:
                            stop_execution_with_error(execution_id, error_msg)
                            return

                        elems_count = len(simple_elems)
                        # reset idx to start from the first element of the child execution
                        idx0 = 0
                        idx, pause = get_next_step_idx(execution_id, execution, simple_elems, idx0, False)
                        logger.debug(f'new child execution execution_id: {execution_id} elems_count: {elems_count} idx0: {idx0} idx: {idx}')

                        # to start from the start of the child execution
                        continue
                    else:
                        logger.debug(f'import procedure number: {number} elem_id: {elem_id}')
                        elems, error_msg = import_procedure_section(execution_id, elem_id)
                        if error_msg is not None:
                            stop_execution_with_error(execution_id, error_msg)
                            return

                        # update elems list
                        simple_elems, error_msg = get_simple_elements(execution_id)
                        if error_msg is not None:
                            stop_execution_with_error(execution_id, error_msg)
                            return
                        
                        elems_count = len(simple_elems)
                        idx0 = idx + 1                            
                        idx, pause = get_next_step_idx(execution_id, execution, simple_elems, idx0, False)
                        logger.debug(f'procedure was imported. execution_id: {execution_id} elems_count: {elems_count} idx0: {idx0} idx: {idx}')
                        
                        continue

        if step:
            executable = step.get('executable')
            if step.get('executed') and (executable is None or executable == 'EXECUTED'):
                logger.debug(f'create_new_run number: {number} elem_id: {elem_id}')
                step, error_msg = create_new_run(execution_id, elem_id)
                if error_msg is not None:
                    stop_execution_with_error(execution_id, error_msg)
                    return
                del step['run_records']
        
        if mode == 'AUTO' and step:
            # Unless the very first element, check for manual input
            if (execution_id != execution_id_0) or ((execution_id == execution_id_0) and (idx > step_idx)):
                # check for pause conditions
                if 'pause_conditions' in execution:
                    pause_conditions = execution['pause_conditions']
                    if pause_conditions.get('on_manual_input'):
                        if requires_manual_input(step):
                            logger.debug(f'Exit automatic execution due to a manual step. execution_id: {execution_id} number: {number} elem_id: {elem_id}')
                            pause = True
                            current_step_id = elem_id
                            break
                    if pause_conditions.get('on_command'):
                        if is_command_step(step):
                            logger.debug(f'Exit automatic execution due to a command step. execution_id: {execution_id} number: {number} elem_id: {elem_id}')
                            pause = True
                            current_step_id = elem_id
                            break
        if pause:
            break
        elif step:
            if 'execution' not in step:
                step['execution'] = {}
            if 'meta_data' not in step['execution']:
                step['execution']['meta_data'] = {}
            step['execution']['meta_data']['status'] = 'RUNNING'
            step['execution']['meta_data']['time_started'] = get_now_utc()
            step['execution']['meta_data']['test_conductor'] = user_name
            step['execution']['meta_data']['status_message'] = 'Starting step'

            try:
                if mode == 'AUTO' and step_executed:
                    step_executed = False
                    delay_sec = execution.get('delay', 0)
                    if delay_sec > 0:
                        time.sleep(delay_sec)
                        
                step_execution = {'meta_data': step['execution']['meta_data']}
                report_step_results(step, step_execution, None)

                update_execution(execution_id, {'current_step_id': elem_id})

                if executable is None or executable == 'EXECUTED':
                    step_out = run_step(step)
                    step_executed = True
                    step_status = step_out['execution']['meta_data']['status']
                    logger.debug(f'execution_id: {execution_id} number: {number} step_status: {step_status}')
                elif executable == 'COMPUTED':
                    step_out, error_msg = compute_step(execution_id, elem_id)
                    step_executed = True
                    if error_msg is None:
                        step_status = step_out['execution']['meta_data']['status']
                        logger.debug(f'execution_id: {execution_id} number: {number} step_status: {step_status}')
                    else:
                        logger.error(error_msg)
                        post_execution_message(execution_id, 'ERROR', error_msg)
                        break
            except:
                error_msg = f'Error when running a step. number: {number} elem_id: {elem_id} details: {traceback.format_exc()}'
                logger.error(error_msg)
                handle_execution_error(execution_id, elem_id, error_msg)
                break

            ## check execution options
            execution, error_msg = get_execution(execution_id)
            if error_msg is not None:
                stop_execution_with_error(execution_id, error_msg)
                return

            mode = execution.get('mode')
            execution_status = execution.get('status')
            logger.debug(f'execution_id: {execution_id} mode: {mode} execution_status: {execution_status}')

            if mode == 'MANUAL':
                break

            # Check for pause
            if mode == 'MANUAL' or execution_status == 'PAUSED':
                break

            # check for pause conditions
            if 'pause_conditions' in execution:
                pause_conditions = execution['pause_conditions']
                if pause_conditions.get('on_error'):
                    if step_status == 'ERROR':
                        logger.debug(f'Exit automatic execution due to an error. execution_id: {execution_id} number: {number}')
                        pause = True
                        break
                if pause_conditions.get('on_fail'):
                    if step_status == 'FAIL':
                        logger.debug(f'Exit automatic execution due to a failure. execution_id: {execution_id} number: {number}')
                        pause = True
                        break
        
            idx, pause = get_next_step_idx(execution_id, execution, simple_elems, idx+1, False)

        while (idx == -1) and execution.get('parent_execution_id'):
            parent_execution_id = execution.get('parent_execution_id')
            parent_procedure_section_id = execution.get('parent_procedure_section_id')
            logger.info(f'resume the parent execution: {parent_execution_id} parent_procedure_section_id: ${parent_procedure_section_id}')
            update_execution(execution_id, {'status': 'IDLE', 'current_step_id': ''})
            parent_execution, error_msg = suspend_resume_execution(execution_id, parent_execution_id)
            if error_msg is not None:
                stop_execution_with_error(execution_id, error_msg)
                return

            dummy, error_msg = switch_execution(execution_id, parent_execution_id)
            if error_msg is not None:
                stop_execution_with_error(execution_id, error_msg)
                return

            execution = parent_execution
            execution_id = execution.get('execution_id')

            try:
                wait_execution_switch(execution_id)
            except:
                logger.error(traceback.format_exc())
                stop_execution_with_error(execution_id, 'Error while waiting for execution to switch')
                return

            simple_elems, error_msg = get_simple_elements(execution_id)
            if error_msg is not None:
                stop_execution_with_error(execution_id, error_msg)
                return
            elems_count = len(simple_elems)

            if parent_procedure_section_id:
                current_step_idx = get_step_idx(simple_elems, parent_procedure_section_id)
                if current_step_idx == -1:
                    msg = f'Procedure step was not found. execution_id: {execution_id} parent_procedure_section_id: {parent_procedure_section_id}'
                    logger.error(msg)
                    stop_execution_with_error(execution_id, msg)
                    return
                # the below logic handles cases where current_step_idx == -1 as well
                idx, pause = get_next_step_idx(execution_id, execution, simple_elems, current_step_idx+1, False)
            else:
                msg = f'Could not determine the starting point of execution. execution_id: {execution_id} parent_procedure_section_id: {parent_procedure_section_id}'
                logger.error(msg)
                stop_execution_with_error(execution_id, msg)
                return

    # if not to pause and there is a next element, advance current_step_id
    if not pause and idx > -1:
        idx, pause = get_next_step_idx(execution_id, execution, simple_elems, idx+1, False)

    if idx == -1:
        current_step_id = ''
    else:
        current_step_id = simple_elems[idx].get('elem_id')

    logger.debug(f'update_execution execution_id: {execution_id} current_step_id: {current_step_id} status: IDLE')
    update_execution(execution_id, {'status': 'IDLE', 'current_step_id': current_step_id})

    return step_out

def stop_execution_with_error(execution_id, msg):
    post_execution_message(execution_id, 'ERROR', msg)
    update_execution(execution_id, {'status': 'IDLE'})

def needs_approval(elem):
    elem_type = elem.get('elem_type')
    procedure_modification_status = elem.get('procedure_modification_status')
    procedure_modification = elem.get('procedure_modification')

    if elem_type == 'STEP' or elem_type == 'PROCEDURE_SECTION':
        if procedure_modification_status == 'MODIFYING' or procedure_modification_status == 'ADDED' or procedure_modification_status == 'DELETED':
            if procedure_modification is None:
                return True
            else:
                approval = procedure_modification.get('approval')
                if approval is None:
                    return True
                else:
                    approval_status = approval.get('status')
                    return approval_status != 'APPROVED'
        else:    
            return False
    else:
        return False

def get_step_idx(simple_elems, current_step_id):
    step_idx = -1
    for idx, elem in enumerate(simple_elems):
        # if current_step_id is not provided, start from the first elem
        if current_step_id == '' or elem.get('elem_id') == current_step_id:
            step_idx = idx
            break
    return step_idx

def get_next_step_idx(execution_id, execution, simple_elems, step_idx, initial):
    """
    get the next step to execute. Search from step_idx (inclusive)
    returns (idx, pause)
    """
    num_simple_elems = len(simple_elems)

    # cache elem_id to parent_id mapping
    parent_id_map = {}
    for simple_elem in simple_elems:
        parent_id_map[simple_elem.get('elem_id')] = simple_elem.get('parent_id')

    prev_parent_id = None
    prev_procedure_section_id = None
    # Find the location of the step
    if step_idx > -1:
        for idx in range(step_idx, num_simple_elems):
            if idx > 0:
                prev_elem = simple_elems[idx-1]
                if prev_elem:
                    prev_parent_id = prev_elem.get('parent_id')
                    prev_procedure_section_id = prev_elem.get('procedure_section_id')

            simple_elem = simple_elems[idx]
            elem_id = simple_elem.get('elem_id')
            # get the element from core to check if breakpoint was set or unset for the element
            # while a previous step was running

            elem, error_msg = get_element(execution_id, elem_id)
            if error_msg is not None:
                post_execution_message(execution_id, 'ERROR', error_msg)
                return -1, True

            elem_type = elem.get('elem_type')
            number = elem.get('number')
            executable = elem.get('executable')
            break_point = elem.get('break_point')
            procedure_section_id = elem.get('procedure_section_id')
            # elem does not have parent_id.  So get it from the map.
            parent_id = parent_id_map.get(elem.get('elem_id'))
            procedure_modification_status = elem.get('procedure_modification_status')

            logger.debug(f'execution_id: {execution_id} step_idx: {step_idx} idx: {idx} number: {number} elem_type: {elem_type} elem_id: {elem_id}' + 
                f' prev_parent_id: {prev_parent_id} parent_id: {parent_id} prev_procedure_section_id: {prev_procedure_section_id} procedure_section_id: {procedure_section_id}' +
                f' break_point: {break_point} initial: {initial}')
            # do not check breakpoint for the starting element
            if not initial:
                initial = False
                if execution is not None:
                    if 'pause_conditions' in execution:
                        pause_conditions = execution['pause_conditions']
                        if pause_conditions.get('on_break_point'):
                            if break_point == 'ACTIVE':
                                logger.debug(f'Hit a breakpoint. execution_id: {execution_id} number: {number}')
                                return idx, True
                        if pause_conditions.get('on_section_end'):
                            if elem_type == 'SECTION' or ((prev_parent_id is not None) and (parent_id != prev_parent_id)):
                                logger.debug(f'Hit a section boundary. execution_id: {execution_id} number: {number}')
                                return idx, True
                        if pause_conditions.get('on_procedure_end'):
                            if elem_type == 'PROCEDURE_SECTION' or ((prev_procedure_section_id is not None) and (procedure_section_id != prev_procedure_section_id)):
                                logger.debug(f'Hit a procedure boundary. execution_id: {execution_id} number: {number}')
                                return idx, True

            if procedure_modification_status == 'MODIFIED' or procedure_modification_status == 'MODIFYING_OLD':
                logger.debug(f'skip redlined step. number: {number} procedure_modification_status: {procedure_modification_status}')
                # skip
                continue
            elif procedure_modification_status == 'DELETED':
                if needs_approval(elem):
                    msg = f'Redline step needs an approval. execution_id: {execution_id} number: {number}'
                    post_execution_message(execution_id, 'INFO', msg)
                    return idx, True
                else:
                    logger.debug(f'skip redlined step. number: {number} procedure_modification_status: {procedure_modification_status}')
                    # skip
                    continue
            else:
                if needs_approval(elem):
                    msg = f'Redline step needs an approval. execution_id: {execution_id} number: {number}'
                    post_execution_message(execution_id, 'INFO', msg)
                    return idx, True
        
            if elem_type == 'STEP' and (executable is None or executable == 'EXECUTED' or executable == 'COMPUTED'):
                return idx, False
            elif elem_type == 'PROCEDURE_SECTION':
                step, error_msg = get_execution_step(execution_id, elem_id)
                if error_msg is not None:
                    post_execution_message(execution_id, 'ERROR', error_msg)
                    return -1, True
                    
                callable = step.get('execution_user_input', {}).get('callable')
                imported = step.get('imported')

                if callable:
                    return idx, False
                else:
                    if imported:
                        # skip
                        continue
                    else:
                        return idx, False

    return -1, False

def requires_manual_input(elem):
    if elem and elem.get('elem_type') == 'STEP':
        step_type = elem.get('step_type')
        if 'MANUAL' in step_type:
            return True

        if step_type == 'CUSTOM_SCRIPT':
            if 'execution_user_input' in elem:
                execution_user_input = elem['execution_user_input']
                if 'inputs' in execution_user_input:
                    inputs = execution_user_input['inputs']
                    for input in inputs:
                        if input.get('phase') == 'EXECUTION':
                            return True

                if 'entries' in execution_user_input:
                    entries = execution_user_input['entries']
                    for entry in entries:
                        if 'entry_inputs' in entry:
                            entry_inputs = entry['entry_inputs']
                            for entry_input in entry_inputs:
                                if entry_input.get('phase') == 'EXECUTION':
                                    return True
    return False

def is_command_step(elem):
    if elem and elem.get('elem_type') == 'STEP':
        step_type = elem.get('step_type')
        if step_type.startswith('CMD') or step_type == 'CUSTOM_SCRIPT':
            return True
    return False

class WorkerProcess(object):
    def __init__(self, name):
        # logger.debug('create a worker')
        self.name = name
        self._init_pool()
        # cache run_mode and step for halt API
        self.execution_id = None
        self.run_mode = None
        # future of the result
        self.future = None

    def _init_pool(self):    
        # logger.debug('worker _init_pool')
        self.pool = ProcessPoolExecutor(max_workers=1)
        fut = self.pool.submit(get_pid)
        self.pid = fut.result()
        logger.info(f'worker _init_pool pid: {self.pid} name: {self.name}')        

    def done_callback(self, context):
        # Note context is the same as self.future when the task was submitted.
        if context is self.future:
            logger.info(f'worker done_callback clear states. pid: {self.pid} name: {self.name} execution_id: {self.execution_id} run_mode: {self.run_mode} future: {self.future} context: {context}')
            # This is a guard to ensure the states are re-set only once by reset or by done_callback
            if self.execution_id is not None:
                self.execution_id = None
                self.run_mode = None
                self.future = None
        else:
            logger.info(f'worker done_callback do not clear states. pid: {self.pid} name: {self.name} execution_id: {self.execution_id} run_mode: {self.run_mode} future: {self.future} context: {context}')

    def reset(self):
        logger.info(f'worker reset pid: {self.pid} name: {self.name} execution_id: {self.execution_id}')

        try:
            os.kill(self.pid, signal.SIGTERM)
        except:
            logger.warning(f'Error when killing worker process. pid: {self.pid} error: {traceback.format_exc()}')

        # Wait until the process is killed
        time_start = time.time()
        sigterm_failed = False
        while True:
            logger.info(f'Waiting for worker process termination. pid: {self.pid} name: {self.name} execution_id: {self.execution_id}')
            if self.pid in psutil.pids():
                if (time.time() - time_start) > 5.0:
                    logger.warning(f'Failed to terminate worker process. pid: {self.pid} name: {self.name} execution_id: {self.execution_id}')
                    sigterm_failed = True
                    break
            else:
                logger.info(f'worker process terminated. pid: {self.pid} name: {self.name}')
                break
            time.sleep(0.1)

        if sigterm_failed:
            try:
                os.kill(self.pid, signal.SIGKILL)
            except:
                logger.warning(f'Error when force killing worker process. pid: {self.pid} error: {traceback.format_exc()}')
            
            time_start = time.time()
            while True:
                logger.info(f'Waiting for worker process kill. pid: {self.pid} name: {self.name} execution_id: {self.execution_id}')
                if self.pid in psutil.pids():
                    if (time.time() - time_start) > 5.0:
                        logger.warning(f'Failed to kill worker process. pid: {self.pid} name: {self.name} execution_id: {self.execution_id}')
                        break
                else:
                    logger.info(f'worker process killed. pid: {self.pid} name: {self.name}')
                    break
                time.sleep(0.1)

        # below function raises an exception since the child process is already killed.
        # Does not seem to need this.
        # self.pool.shutdown(wait=False)
        self._init_pool()

        # Re-set state after recreating the pool so that this pool is not used until the pool is re-created.
        # This is a guard to ensure the states are re-set only once by reset or by done_callback
        logger.info(f'worker reset checking pid: {self.pid} name: {self.name} execution_id: {self.execution_id}')
        if self.execution_id is not None:
            self.execution_id = None
            self.run_mode = None
            self.future = None

    def submit_func(self, func, step, execution_id, elem_id, user_name, run_mode):
        try:
            logger.info(f'worker submit_func pid: {self.pid} name: {self.name} execution_id: {execution_id} elem_id: {elem_id} user_name: {user_name}')
            # cache step and run_mode for halt API
            self.execution_id = execution_id
            self.run_mode = run_mode

            self.future = self.pool.submit(func, step, execution_id, elem_id, user_name, run_mode)
            self.future.add_done_callback(self.done_callback)
            return self.future
        except BrokenProcessPool as ex:
            logger.warning('pool is broken. restart worker process')
            # restart the worker process to heal the broken worker
            self.reset()
            # then report the error to the user
            raise Exception('Error when running step') from ex
        except Exception as ex:
            logger.warning(f'submit error: {traceback.format_exc()}')
            # reset worker to reinit state of the worker
            self.reset()
            # then report the error to the user
            raise Exception('Error when running step') from ex

    def is_idle(self):

        logger.debug(f'is_idle name: {self.name} pid: {self.pid} execution_id: {self.execution_id} future: {self.future}')
        return self.execution_id is None
class WorkerPool(object):   
    def __init__(self, size):
        self.size = size
        self.current_idx = 0
        self.workers = []

        for i in range(size):
            worker = WorkerProcess(f'worker-{i}')
            logger.debug(f'worker created name: {worker.name} pid: {worker.pid}')
            self.workers.append(worker)        

    def submit_func(self, func, step, execution_id, elem_id, user_name, run_mode):
        current_idx = self.current_idx
        num_idle_workers = 0
        for worker in self.workers:
            if worker.is_idle():
                num_idle_workers += 1
        logger.debug(f'idle workers: {num_idle_workers} out of {len(self.workers)}')
        for i in range(current_idx, current_idx + self.size):
            idx = i % self.size
            worker = self.workers[idx]
            self.current_idx = (i+1) % self.size
            if worker.is_idle():
                logger.info(f'submit to worker execution_id: {execution_id} elem_id: {elem_id} worker name: {worker.name} pid: {worker.pid}')

                return worker.submit_func(func, step, execution_id, elem_id, user_name, run_mode)
        raise Exception('No worker is available')  

    def switch_execution(self, execution_id, target_execution_id):
        worker_found = False
        for worker in self.workers:
            if (worker.execution_id == execution_id) and (not worker.is_idle()):
                worker.execution_id = target_execution_id
                logger.info(f'switch_execution switched name: {worker.name} pid: {worker.pid} execution_id: {execution_id} target_execution_id: {target_execution_id}')
                worker_found = True
                break
        
        if not worker_found:
            raise Exception(f'Failed to switch execution. No worker found for execution_id: {execution_id}')

    def cancel_run(self, execution_id):
        worker_found = False
        run_mode = None

        for worker in self.workers:
            is_idle = worker.is_idle()
            logger.debug(f'cancel_run checking workers execution_id: {execution_id} worker.execution_id: {worker.execution_id} is_idle: {is_idle}')
            if (worker.execution_id == execution_id) and (not is_idle):
                worker_found = True
                run_mode = worker.run_mode

                logger.info(f'Cancel worker name: {worker.name} execution_id: {execution_id} run_mode: {run_mode}')
                worker.reset()
                break

        if worker_found:
            return True, run_mode
        else:
            logger.warning(f'No worker found for execution_id: {execution_id}')
            return False, run_mode    


def exec_api(*args0, **kwargs0):
    def decorator(func):
        @wraps(func)
        def wrapper(*args):
            handler = args[0]

            required_scopes = kwargs0.get('required_scopes', [])
            event_name = kwargs0.get('event', '')
            event_description = kwargs0.get('description', '')

            if required_scopes:
                auth = handler.request.headers.get('Authorization')
                # logger.debug('Authorization header: %s', auth)
                if auth:
                    parts = auth.split()

                    if parts[0].lower() != 'bearer':
                        handler._transforms = []
                        handler.set_status(401)
                        handler.finish(json.dumps({'message': 'invalid authorization header'}))
                    elif len(parts) == 1:
                        handler._transforms = []
                        handler.set_status(401)
                        handler.finish(json.dumps({'message': 'invalid authorization header'}))
                    elif len(parts) > 2:
                        handler._transforms = []
                        handler.set_status(401)
                        handler.finish(json.dumps({'message': 'invalid authorization header'}))
                    else:
                        jwt_token = parts[1]

                        try:
                            jwt_decoded = jwt.decode(
                                jwt_token,
                                public_pem,
                                algorithms=['RS256'],
                                options=jwt_options
                            )

                            # logger.debug('jwt_decoded: %s', json.dumps(jwt_decoded, indent=4))
                            actual_scopes = list(map(lambda scope : scope.get('scope', '') if isinstance(scope, dict) else scope, jwt_decoded['scopes']))
                            # logger.debug('required_scopes: %s', required_scopes)
                            # logger.debug('actual_scopes: %s', actual_scopes)
                            user_name = jwt_decoded.get('username', '')
                            
                            set_required = set(required_scopes)
                            set_actual = set(actual_scopes)

                            if len(set_required) > 0 and len(set_required.intersection(set_actual)) == 0:
                                handler.set_status(401)
                                handler.finish(json.dumps({'message': 'JWT scope requirement was not met.'}))
                            else:
                                # Make jwt_token available to the request handler
                                handler.jwt_token = jwt_token
                                handler.jwt_decoded = jwt_decoded

                                # func may contain async calls. So the wrapper is going to return before func is done.
                                # Make log data available to the request handler and let handler.finish() generate log.
                                # event_description will be used as message in finish method but itself won't be included in the log 
                                # by json_log_config.
                                
                                handler.log_dict = {'event': event_name, 'event_description': event_description, 'user_name': user_name}
                                return func(*args)

                        except Exception as e:
                            msg = f'Invalid JWT token: {traceback.format_exc()}'
                            logger.error(msg)
                            handler.set_status(401)
                            handler.finish(json.dumps({'message': msg}))
                        
                else:
                    logger.warning('Authorization header was not provided.')
                    handler.set_status(401)
                    handler.finish(json.dumps({'message': 'Authorization header was not provided.'}))
            else:
                handler.log_dict = {'event': event_name, 'event_description': event_description}
                return func(*args)                

        return wrapper
    return decorator


class RequestLogHandler(RequestHandler):

    def __init__(self, application, request, **kwargs):
        super(RequestLogHandler, self).__init__(application, request, **kwargs)
        self.log_dict = OrderedDict()

    def finish(self, chunk=None):
        # logger.info('RequestLogHandler self.request.method: %s', self.request.method)
        # logger.info('RequestLogHandler self.request.uri: %s', self.request.uri)

        super(RequestLogHandler, self).finish(chunk)

        if chunk:
            try:
                self.log_dict['data'] = json.loads(chunk)
            except:
                pass

        if self.get_status() >= 200 and self.get_status() < 300:
            if self.request.method == 'GET':
                pass
            else:
                logger.info(self.log_dict.get('event_description', ''), extra=self.log_dict)
        else:
            logger.error(self.log_dict.get('event_description', ''), extra=self.log_dict)

                  
class ExecutionHandler(RequestLogHandler):
    @exec_api(required_scopes=['execute:wsts', 'execute:testbed', 'execute:sit', 'execute:other'], event='register_execution', description='Register an execution')
    def put(self, execution_id):
        # logger.debug('ExecutionHandler PUT execution_id: %s', execution_id)
        
        try:
            venue_info = json_decode(self.request.body)
            # logger.debug('ExecutionHandler PUT venue_info: %s', json.dumps(venue_info))
            self.application.state_manager.set_config_value(execution_id, 
                'execution_id', execution_id)
            self.application.state_manager.set_config_value(execution_id, 
                'venue_service_address', venue_info.get('ampcs_address', ''))
            self.application.state_manager.set_config_value(execution_id, 
                'venue_sse', venue_info.get('sse_address', ''))
            self.application.state_manager.set_config_value(execution_id, 
                'venue_name', venue_info.get('name', ''))
            self.application.state_manager.set_config_value(execution_id, 
                'venue_id', venue_info.get('venue_id', ''))  
            self.application.state_manager.set_config_value(execution_id, 
                'venue_type', venue_info.get('type', '')) 

            self.set_status(204)
            self.finish()
        except Exception as ex:
            logger.exception('Error while setting venue info for execution')            
            err_msg = str(ex)
            self.set_status(400)
            
            err_dict = {'message': err_msg,
                        'details': [traceback.format_exc()],
                        'error_type': 'INGENIUM_SERVICE_ERROR',
                        'error_source': 'EXECUTION_SERVICE',
                        'http_code_at_source': 0}
                            
            self.finish(json.dumps(err_dict, indent=4))
            
    @exec_api(required_scopes=['execute:wsts', 'execute:testbed', 'execute:sit', 'execute:other'], event='unregister_execution', description='Unregister an execution')
    def delete(self, execution_id):
        logger.debug('ExecutionHandler DELETE execution_id: %s', execution_id)
        
        try:
            self.application.state_manager.delete_execution(execution_id)
            self.set_status(204)
            self.finish()
        except Exception as ex:
            logger.exception('Error while unregistering an execution')            
            err_msg = str(ex)
            self.set_status(400)
            
            err_dict = {'message': err_msg,
                        'details': [traceback.format_exc()],
                        'error_type': 'INGENIUM_SERVICE_ERROR',
                        'error_source': 'EXECUTION_SERVICE',
                        'http_code_at_source': 0}
                            
            self.finish(json.dumps(err_dict, indent=4))

class RunHandler(RequestLogHandler):
    @gen.coroutine
    @exec_api(required_scopes=['execute:wsts', 'execute:testbed', 'execute:sit', 'execute:other'], event='run_step', description='Run a step')
    def post(self, execution_id):
        run_mode = self.get_argument('run_mode', 'SYNC')
        elem_id = self.get_argument('elem_id', '')
        
        end_time_str = None
        step = None
        try:
            if self.request.body:
                step = json_decode(self.request.body)
            else:
                step = None

            venue_token_dict = copy.deepcopy(self.jwt_decoded)
            time_now = time.time()
            venue_token_dict['exp'] = int(time_now)+3600
            venue_token_dict['iat'] = int(time_now)
            exec_venue_jwt_encoded = jwt.encode(venue_token_dict,
                                                exec_venue_private_pem,
                                                algorithm='RS256')
            # PyJWT >= 2 returns a str; older versions returned bytes. Normalize to str.
            exec_venue_jwt_str = exec_venue_jwt_encoded.decode('utf-8') if isinstance(exec_venue_jwt_encoded, bytes) else exec_venue_jwt_encoded

            # set token for venue service
            self.application.state_manager.set_config_value(execution_id, 'venue_token', exec_venue_jwt_str)
            # set the original ingenium token so that the embedded code can talk to venue config service
            self.application.state_manager.set_config_value(execution_id, 'ing_token', self.jwt_token)   

            self.application.state_manager.set_config_value(execution_id, 'run_mode', run_mode)       
            
            ### Execute step embedded code

            try:
                user_name = self.log_dict.get('user_name')
                fut = self.application.worker_pool.submit_func(run_execution, step, execution_id, elem_id, user_name, run_mode)
            except:
                err_dict = {'message': f'Failed to run step. execution_id: {execution_id} elem_id: {elem_id}',
                            'details': [traceback.format_exc()],
                            'error_type': 'INGENIUM_SERVICE_ERROR',
                            'error_source': 'EXECUTION_SERVICE',
                            'http_code_at_source': 0}
                
                self.set_status(400)                            
                self.finish(json.dumps(err_dict, indent=4))

                return

            if run_mode == 'ASYNC':
                self.set_status(202)
                self.finish(json.dumps(step))
                return

            # For SYNC mode, wait for the sub process to finish
            # and get the results
            output_step = yield fut

            end_time_str = get_now_utc()
            output_step['execution']['meta_data']['time_completed'] = end_time_str   

            self.set_status(200)                
            self.finish(json.dumps(output_step, indent=4))

        except Exception as ex:
            logger.exception('Error while running a step')    
                   
            err_msg = str(ex)
            
            err_dict = {'message': err_msg,
                        'details': [traceback.format_exc()],
                        'error_type': 'INGENIUM_SERVICE_ERROR',
                        'error_source': 'EXECUTION_SERVICE',
                        'http_code_at_source': 0}

            end_time_str = get_now_utc()

            if step is None:
                ic.ing_token = self.jwt_token
                step, error_msg = get_execution_step(execution_id, elem_id)
            
            if step is None:
                self.set_status(400)                            
                self.finish(json.dumps(err_dict, indent=4))
            else:
                step['execution']['meta_data']['time_completed'] = end_time_str
                step['execution']['meta_data']['status'] = 'ERROR'
                step['execution']['meta_data']['error'] = err_dict

                self.set_status(200)
                self.finish(json.dumps(step, indent=4))
            
class ConfigHandler(RequestLogHandler):
    @exec_api(required_scopes=['execute:wsts', 'execute:testbed', 'execute:sit', 'execute:other'], event='get_config_value', 
        description='Get value of a configuration variable of an execution')
    def get(self, execution_id):
        # logger.debug('ConfigHandler GET execution_id: %s', execution_id)

        try:
            parameter_name = self.get_argument('parameter_name', None)

            if not parameter_name:
                logger.warn('parameter_name is empty. simply return')
                self.set_status(400)
                err_dict = {'message': 'parameter_name is empty'}
                self.finish(json.dumps(err_dict, indent=4))
                return

            run_response = self.application.state_manager.get_config_value(execution_id, 
                parameter_name)
            # logger.debug('ConfigHandler get run_response: %s', run_response)
            
            try:
                value = ast.literal_eval(run_response)
                self.set_status(200)
                res_dict = {'name': parameter_name,
                            'value': value}               
                self.finish(json.dumps(res_dict, indent=4))
                
            except:
                msg = 'Failed to parse value: ' + run_response
                logger.error(msg)
                raise Exception(msg)            

        except:
            err_msg = traceback.format_exc()
            logger.error(err_msg)
            self.set_status(400)
            err_dict = {'message': err_msg}
            self.finish(json.dumps(err_dict, indent=4))            

class VariableHandler(RequestLogHandler):
    @exec_api(required_scopes=['execute:wsts', 'execute:testbed', 'execute:sit', 'execute:other'], event='get_variable_value', description='Get value of a step variable')
    def get(self, execution_id):
        # logger.debug('ValueHandler GET execution_id: %s', execution_id)

        try:
            variable_name = self.get_argument('variable_name', None)

            if not variable_name:
                logger.warn('variable_name is empty. simply return')
                self.set_status(400)
                err_dict = {'message': 'variable_name is empty'}
                self.finish(json.dumps(err_dict, indent=4))
                return

            value = self.application.state_manager.get_variable_value(execution_id, 
                variable_name)
            # logger.debug('VariableHandler value: %s', value)

            self.set_status(200)
            
            res_dict = {'name': variable_name,
                        'value': value}
            self.finish(json.dumps(res_dict, indent=4))

        except:
            err_msg = traceback.format_exc()
            logger.error(err_msg)
            self.set_status(400)
            err_dict = {'message': err_msg}
            self.finish(json.dumps(err_dict, indent=4))

class HaltHandler(RequestLogHandler):

    @exec_api(required_scopes=['execute:wsts', 'execute:testbed', 'execute:sit', 'execute:other'], event='halt_kernel', 
        description='Halt the execution if the kernel is running a step')
    def post(self, execution_id):
        logger.info(f'HaltHandler POST execution_id: {execution_id}')
        try:
            # set ing_token in configuration so that it may be used to report the canceled run to Core for async run
            # logger.debug(f'cancel run jwt_token: {self.jwt_token}')
            ic.ing_token = self.jwt_token

            current_step_info = ingenium_library.get_current_step_cache(execution_id)
            logger.info(f'HaltHandler execution_id: {execution_id}', extra={'data': current_step_info})

            step_execution = {
                'meta_data': {
                    'status': 'FAIL'
                },
                'results': {
                    'log_file_url': ''
                }
            }
            
            if current_step_info.get('current_step_type') == 'CUSTOM_SCRIPT':
                number = current_step_info.get('current_step_number')
                custom_script_session_id = current_step_info.get('custom_script_session_id')
                if custom_script_session_id:
                    logger.debug(f'HaltHandler execution_id: {execution_id} number: {number} custom_script_session_id: {custom_script_session_id}')
                    ingenium_library.reload_execution_cache(execution_id)
                    
                    status_response = None
                    try:
                        status_response = ingenium_library.get_script_status(custom_script_session_id)
                        if status_response.status_code == 200:
                            script_status_info = json.loads(status_response.text)
                            logfile_url = script_status_info.get('logfile_url')

                            if logfile_url:
                                # Note that states in output_json are not used to update execution states for the execution since the step was canceled,
                                # which is consistent with the behavior of EHA steps.
                                fileserver_logfile_url, output_json = ingenium_library.process_cs_files(logfile_url, custom_script_session_id)
                                step_execution['results']['log_file_url'] = fileserver_logfile_url
                            else:
                                logger.warning(f'Failed to get custom script logfile_url.')
                        else:
                            logger.warning(f'Failed to get custom script status. status_code: {status_response.status_code}')
                    except Exception as ex:        
                        msg = 'Error when getting log file of custom script during halt'
                        error_obj = ingenium_library.create_step_error(message=msg,
                                        details=[traceback.format_exc()],
                                        error_type=ErrorType.QUERY_ERROR.value,
                                        error_source=ErrorSource.VENUE_SERVICE.value,
                                        http_code_at_source=0)
                        # log statement
                        logger.warning(msg, extra = {
                            "event": EventName.CUSTOM_SCRIPT_STATUS.value,
                            "data": error_obj
                        })

                    ingenium_library.halt_script(custom_script_session_id)
                else:
                    logger.warning(f'Cannot halt custom script process. custom_script_session_id was not found.')

            run_exists, run_mode = self.application.worker_pool.cancel_run(execution_id)
            logger.debug(f'cancel_run called. execution_id: {execution_id} run_exists: {run_exists} run_mode: {run_mode}')

            # report results
            if run_exists:
                current_step_id = current_step_info.get('current_step_id')
                current_step_type = current_step_info.get('current_step_type')

                if current_step_id and current_step_type:
                    report_step_results2(execution_id, current_step_id, step_execution, 'Step execution was canceled')
                
                    # DO NOT advance current_step_id when a step is aborted
                self.set_status(202)
                self.finish()
            else:
                self.set_status(404)
                self.finish()                    
        except:
            err_msg = traceback.format_exc()
            logger.error(err_msg)
            self.set_status(500)
            err_dict = {'message': err_msg}
            self.finish(json.dumps(err_dict, indent=4))

class CopyStateHandler(RequestLogHandler):
    @exec_api(required_scopes=['execute:wsts', 'execute:testbed', 'execute:sit', 'execute:other'], event='copy_execution_state', 
        description='Copy execution state to another execution')
    def post(self, execution_id):
        try:
            target_execution_id = self.get_argument('target_execution_id', None)

            if not target_execution_id:
                logger.warn('target_execution_id is empty. simply return')
                self.set_status(400)
                err_dict = {'message': 'target_execution_id is empty'}
                self.finish(json.dumps(err_dict, indent=4))
                return
            
            res_dict = ingenium_library.copy_execution_state(execution_id, target_execution_id)
            self.set_status(200)
            self.finish(json.dumps(res_dict, indent=4))
        except:
            err_msg = traceback.format_exc()
            logger.error(err_msg)
            self.set_status(400)
            err_dict = {'message': err_msg}
            self.finish(json.dumps(err_dict, indent=4))

class SwitchHandler(RequestLogHandler):
    @exec_api(required_scopes=['execute:wsts', 'execute:testbed', 'execute:sit', 'execute:other'], event='switch_execution', 
        description='Switch work to another execution')
    def post(self, execution_id):
        try:
            target_execution_id = self.get_argument('target_execution_id', None)
            logger.debug(f'switch_execution execution_id: {execution_id} target_execution_id: {target_execution_id}')
            if not target_execution_id:
                self.set_status(400)
                err_dict = {'message': 'target_execution_id is empty'}
                self.finish(json.dumps(err_dict, indent=4))
                return
            
            self.application.worker_pool.switch_execution(execution_id, target_execution_id)

            self.set_status(204)
            self.finish()
        except:
            err_msg = traceback.format_exc()
            logger.error(err_msg)
            self.set_status(400)
            err_dict = {'message': err_msg}
            self.finish(json.dumps(err_dict, indent=4))

class LoggingHandler(RequestLogHandler):

    @exec_api(required_scopes=['admin'], event='update_logging', description='Update logging configuration')
    def post(self):
        # logger.debug('LoggingHandler POST')

        try:
            logging_info = json.loads(self.request.body)
            if 'level' in logging_info:
                logger.setLevel(logging_info['level'])
                self.set_status(204)
                self.finish()
            else:
                err_msg = 'Invalid format of logging info'
                logger.error(err_msg)
                self.set_status(400)
                err_dict = {'message': err_msg}
                self.finish(json.dumps(err_dict))
        except:
            err_msg = traceback.format_exc()
            logger.error(err_msg)
            self.set_status(400)
            err_dict = {'message': err_msg}
            self.finish(json.dumps(err_dict))

    @exec_api(required_scopes=['admin'], event='get_logging', description='Get logging configuration')
    def get(self):
        # logger.debug('LoggingHandler GET')

        log_level = logging.getLevelName(logger.level)

        self.finish(json.dumps({'level': log_level}))

class HealthHandler(RequestLogHandler):
    @exec_api(required_scopes=[], event='get_health', description='Get health status of the service')
    def get(self):
        self.finish(json.dumps({'status': 'OK', 'message': ''}, indent=4))


class ExecutionServer(tornado.web.Application):
    """
    Main Tornado application of Ingenium Execution Server
    """
    def __init__(self, config):
        self.config = config

        num_kernels_min_str = os.environ.get('NUMBER_OF_KERNELS_MIN', '')
        num_kernels_min = 5
        try:
            num_kernels_min = int(num_kernels_min_str)
        except:
            logger.info(f'NUMBER_OF_KERNELS_MIN was not set. Use default of {num_kernels_min}')
        
        self.worker_pool = WorkerPool(num_kernels_min)              
        
        redis_host = self.config.get('redis', 'REDIS_HOST')
        logger.info('REDIS_HOST default: %s', redis_host)
        redis_host = os.getenv('REDIS_HOST', redis_host)
        logger.info('REDIS_HOST: %s', redis_host)        
        
        redis_port_str = self.config.get('redis', 'REDIS_PORT')
        logger.info('REDIS_PORT default: %s', redis_port_str)
        redis_port_str = os.getenv('REDIS_PORT', redis_port_str)
        
        redis_port = 6379
        try:
            redis_port = int(redis_port_str)
        except:
            logger.warn('REDIS port is not an integer: %s', redis_port_str)
        logger.info('REDIS_PORT: %s', redis_port)            
        
        self.state_manager = StateManager(redis_host, redis_port)


        handlers = [(r'/api/v4/executions/([0-9a-zA-Z\-]+)', ExecutionHandler),
                    (r'/api/v4/executions/([0-9a-zA-Z\-]+)/run', RunHandler),
                    (r'/api/v4/executions/([0-9a-zA-Z\-]+)/config_value', ConfigHandler),
                    (r'/api/v4/executions/([0-9a-zA-Z\-]+)/variable_value', VariableHandler),
                    (r'/api/v4/executions/([0-9a-zA-Z\-]+)/copy_state', CopyStateHandler),
                    (r'/api/v4/executions/([0-9a-zA-Z\-]+)/switch', SwitchHandler),
                    (r'/api/v4/executions/([0-9a-zA-Z\-]+)/halt', HaltHandler),
                    (r'/api/v4/logging', LoggingHandler),
                    (r'/api/v4/health', HealthHandler)]

        settings = {}

        tornado.web.Application.__init__(self, handlers, **settings)

if __name__ == '__main__':

    config = ConfigParser()
    config.read('config.ini')

    log_level_str = os.environ.get('LOG_LEVEL', config.get('logging', 'LOG_LEVEL'))
    logger.info('LOG_LEVEL: %s', log_level_str)    
    logger.setLevel(log_level_str)       
    
    app = ExecutionServer(config)
    
    settings = {}

    server = tornado.httpserver.HTTPServer(app, **settings)
    server.listen(int(os.environ.get('HTTP_PORT', app.config.getint('server', 'HTTP_PORT'))))
    logger.info('New Ingenium Execution Server started (port=%d)', int(os.environ.get('HTTP_PORT', app.config.getint('server', 'HTTP_PORT'))))

    if os.environ.get('DEV', app.config.get('server', 'DEV')).lower() == "true":
        tornado.autoreload.start()
        for dir_name, _, files in os.walk('.'):
            # debug mode only, auto-reload when files change.
            [tornado.autoreload.watch(dir_name + '/' + f) for f in files if f.endswith('.py') and not f.startswith('.')]       

    tornado.ioloop.IOLoop.current().start()
    os._exit(0)
    