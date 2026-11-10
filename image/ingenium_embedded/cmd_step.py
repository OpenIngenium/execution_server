from . import ingenium_config as ic
from . import ingenium_library as ing_lib
from .ingenium_library import ing_execution, get_dict_value, create_step_error, return_step_with_error, StepExecutionError, report_step_results, determine_cmd_failure
import traceback
import time
from .logging_util import logger
import copy
from .verification_lib import FSWVerify, HWVerify
import os

@ing_execution
def run(step):

    if ic.manual_input_variables.get("step_function_name") and ic.manual_input_variables.get("step_function_name").get('actual_value') == "run_dummy":
        return run_dummy(step)

    results = copy.deepcopy(step["execution_user_input"])
    for entry in results["entries"]:
        entry['radiated'] = False
        entry['verified'] = False
        entry['radiated_time'] = ''
        entry['verified_time'] = ''

    step["execution"]["results"] = results

    data_path = results.get('data_path')
    if not data_path:
        msg = "Data path was not provided"
        error_obj = create_step_error(message=msg,
                        details=[],
                        error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                        error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                        http_code_at_source=0)

        logger.error(msg, extra = {
            "event": ing_lib.EventName.DATA_PATH_CHECK.value,
            "data": error_obj
        })

        return return_step_with_error(step, error_obj)

    for entry in results["entries"]:
        # update status
        msg = 'Dispatching command: {}'.format(entry["cmd_string"])
        logger.info(msg, extra = {
            "event": ing_lib.EventName.DISPATCH_COMMAND_FSW.value
        })
        step_execution = {
            'meta_data': {
                'status': 'RUNNING', 
                'status_message': msg
            },
            'results': results
        }
        report_step_results(step, step_execution, None)

        if entry["verify"] == True:
            if entry["hw_fsw"] == "FSW":
                try:
                    fsw = FSWVerify(entry=entry, data_path=data_path, step=step)
                    fsw.fsw_command_verification()
                except StepExecutionError as ex:
                    msg = "CommandFSW query and/or verification to venue failed"
                    # log statement
                    logger.error(msg, extra = {
                        "event": ing_lib.EventName.VERIFY_COMMAND.value,
                        "data": {
                            "message": msg,
                            "error_type": ing_lib.ErrorType.DISPATCH_ERROR.value,
                            "error_source": ing_lib.ErrorSource.EMBEDDED_CODE.value,
                            "http_code_at_source": 0,
                            "details": [str(ex.error_obj)]
                        }
                    })
                    return return_step_with_error(step, ex.error_obj)
                except Exception as ex:
                    msg = "CommandFSW query and/or verification to venue failed"
                    # log statement
                    error_obj = create_step_error(message=msg,
                                    details=[traceback.format_exc()],
                                    error_type=ing_lib.ErrorType.DISPATCH_ERROR.value,
                                    error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                                    http_code_at_source=0)

                    logger.error(msg, extra = {
                        "event": ing_lib.EventName.DISPATCH_COMMAND.value,
                        "data": error_obj
                    })
                    return return_step_with_error(step, error_obj)

            elif entry["hw_fsw"] == "HW":
                try:
                    hw = HWVerify(entry=entry, data_path=data_path, step=step)
                    hw.hw_command_verfication()
                except StepExecutionError as ex:
                    msg = "CommandHW query and/or verification to venue failed"
                    # log statement
                    logger.error(msg, extra = {
                        "event": ing_lib.EventName.VERIFY_COMMAND.value,
                        "data": {
                            "message": msg,
                            "error_type": ing_lib.ErrorType.DISPATCH_ERROR.value,
                            "error_source": ing_lib.ErrorSource.EMBEDDED_CODE.value,
                            "http_code_at_source": 0,
                            "details": [str(ex.error_obj)]
                        }
                    })
                    return return_step_with_error(step, ex.error_obj)
                except Exception as ex:
                    msg = "CommandHW query and/or verification to venue failed"
                    # log statement
                    error_obj = create_step_error(message=msg,
                                    details=[traceback.format_exc()],
                                    error_type=ing_lib.ErrorType.DISPATCH_ERROR.value,
                                    error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                                    http_code_at_source=0)

                    logger.error(msg, extra = {
                        "event": ing_lib.EventName.DISPATCH_COMMAND.value,
                        "data": error_obj
                    })
                    return return_step_with_error(step, error_obj)
        else:
            # if verify == False, just send the command and return results. Logic below separates between FSW and HW commands.
            if entry["hw_fsw"] == "FSW":
                try:
                    cmd_dispatch = ing_lib.CommandFSW(data_path=data_path, command_string=entry["cmd_string"], validate=True,
                                                      string_selection=entry.get('string_selection', 'DEFAULT'), timeout=get_dict_value(entry, "timeout", ic.cmd_timeout))
                except StepExecutionError as ex:
                    msg = "CommandFSW query to venue failed"
                    # log statement
                    logger.error(msg, extra = {
                        "event": ing_lib.EventName.DISPATCH_COMMAND.value,
                        "data": {
                            "message": msg,
                            "error_type": ing_lib.ErrorType.QUERY_ERROR.value,
                            "error_source": ing_lib.ErrorSource.VENUE_SERVICE.value,
                            "http_code_at_source": 400,
                            "details": [str(ex.error_obj)]
                        }
                    })

                    return return_step_with_error(step, ex.error_obj)
                except Exception as ex:
                    msg = "CommandFSW query to venue failed"
                    # log statement
                    error_obj = create_step_error(message=msg,
                                    details=[traceback.format_exc()],
                                    error_type=ing_lib.ErrorType.DISPATCH_ERROR.value,
                                    error_source=ing_lib.ErrorSource.VENUE_SERVICE.value,
                                    http_code_at_source=400)

                    logger.error(msg, extra = {
                        "event": ing_lib.EventName.DISPATCH_COMMAND.value,
                        "data": error_obj
                    })

                    return return_step_with_error(step, error_obj)


            elif entry["hw_fsw"] == "HW":
                try:
                    cmd_dispatch = ing_lib.CommandHW(data_path=data_path, command_stem=entry["cmd_string"], 
                                                     string_selection=entry.get('string_selection', 'DEFAULT'), timeout=get_dict_value(entry, "timeout", ic.cmd_timeout))
                except StepExecutionError as ex:
                    msg = "CommandHW query to venue failed"
                    # log statement
                    logger.error(msg, extra = {
                        "event": ing_lib.EventName.DISPATCH_COMMAND.value,
                        "data": {
                            "message": msg,
                            "error_type": ing_lib.ErrorType.QUERY_ERROR.value,
                            "error_source": ing_lib.ErrorSource.VENUE_SERVICE.value,
                            "http_code_at_source": 400,
                            "details": [str(ex.error_obj)]
                        }
                    })
                    return return_step_with_error(step, ex.error_obj)
                except Exception as ex:
                    msg = "CommandFSW query to venue failed"
                    # log statement
                    error_obj = create_step_error(message=msg,
                                    details=[traceback.format_exc()],
                                    error_type=ing_lib.ErrorType.DISPATCH_ERROR.value,
                                    error_source=ing_lib.ErrorSource.VENUE_SERVICE.value,
                                    http_code_at_source=400)

                    logger.error(msg, extra = {
                        "event": ing_lib.EventName.DISPATCH_COMMAND.value,
                        "data": error_obj
                    })

                    return return_step_with_error(step, error_obj)

            entry.update({
                "radiated": True if "dispatchTime" in cmd_dispatch else False,
                "radiated_time": cmd_dispatch["dispatchTime"] if "dispatchTime" in cmd_dispatch else None,
                "verified": False,
                "verified_time": ""
            })

        # adding artificial 1 second delay between each sent cmd
        time.sleep(ic.cmd_delay_seconds)
        
        is_failure = determine_cmd_failure(step.get("step_type"), entry.get("verify"), entry)

        if is_failure:
            break

    # logic for step level status
    for entry in results["entries"]:
        if entry["verify"] == True:
            if entry["verified"] == False:
                step["execution"]["meta_data"]["status"] = "FAIL"
                break
            else:
                step["execution"]["meta_data"]["status"] = "PASS"

        else:
            if entry["radiated"] == False:
                step["execution"]["meta_data"]["status"] = "FAIL"
                break
            else:
                step["execution"]["meta_data"]["status"] = "PASS"


    step["execution"]["meta_data"]["status_message"] = ""

    return step


def run_dummy(step):

    print('cmd_step.run_dummy()')
    queries = copy.deepcopy(step['execution_user_input'])

    outputs = []
    for query in queries["entries"]:

        cmd_data =  {
            "hw_fsw": "FSW",
            "timeout": 10,
            "cmd_string": "flight 123 12 1",
            "verify": False,
            "radiated": True,
            "radiated_time": "2017-032T00:23:03",
            "verified": False,
            "verified_time": "2017-032T00:22:50"
        }

        outputs.append(cmd_data)

    results = {
        "entries": outputs
    }
    step['execution']['results'] = results
    step['execution']['meta_data']['status'] = 'PASS'
    return step

@ing_execution
def run_dummy_get_session_info(step):
    """
    This is a function used only for test. Returns the current session information in the results.
    Note that pid is for debugging and not a part of specification of the step.
    """

    print('cmd_step.run_dummy_get_session_info()')
    execution_user_input = copy.deepcopy(step['execution_user_input'])

    results = {
        'entries': ic.ampcs_session_information,
        'pid': os.getpid()
    }
    step['execution']['results'] = results
    step['execution']['meta_data']['status'] = 'PASS'
    return step