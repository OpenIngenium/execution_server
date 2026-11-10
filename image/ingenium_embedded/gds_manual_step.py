from . import ingenium_config as ic
from . import ingenium_library as ing_lib
from .ingenium_library import ing_execution, create_step_error, return_step_with_error, StepExecutionError, report_step_results
from .logging_util import logger
import copy
import traceback
import os

@ing_execution
def run(step):
    """
    This function implements the GDSStep step.

    All Ingenium Step Functions only accept the step JSON as both an input and as an output.

    """
    # Pull out the GDSStep definition of the step
    results = copy.deepcopy(step["execution_user_input"])
    # Populate the query results
    results['venue_id'] = ic.venue_id
    results['venue_name'] = ic.venue_name
    results['venue_service_address'] = ic.venue_service_address

    step["execution"]["results"] = results

    # Check input values
    for entry in results["entries"]:
        data_path = entry.get('data_path', '').strip()
        if data_path == '':
            msg = 'data path was not provided'
            error_obj = create_step_error(message=msg,
                error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                details=[],
                http_code_at_source=0)

            logger.error(msg, extra={
                "event": ing_lib.EventName.USER_INPUT_VALIDATION.value,
                "data": error_obj
            })

            return return_step_with_error(step, error_obj)

    default_cmd_string = results.get('default_cmd_string', 'AB')

    # stop MTAK
    msg = 'Shutting down MTAK'
    # log statement
    logger.info(msg, extra= {
        "event": ing_lib.EventName.MTAK_SHUTDOWN.value
    })

    step_execution = {
        'meta_data': {
            'status': 'RUNNING', 
            'status_message': msg
        },
        'results': results
    }
    report_step_results(step, step_execution, None)    

    try:
        ing_lib.ShutdownMTAK()
    except StepExecutionError as ex:
        msg = "ShutdownMTAK failed"
        # log statement
        logger.error(msg, extra= {
            "event": ing_lib.EventName.MTAK_SHUTDOWN.value,
            "data": {
                "message": msg,
                "error_source": ing_lib.ErrorSource.VENUE_SERVICE.value,
                "error_type": ing_lib.ErrorType.VENUE_SERVICE_ERROR.value,
                "http_code_at_source": 400,
                "details": [str(ex.error_obj)]
            }
        })
        return return_step_with_error(step, ex.error_obj)
    except:
        msg = "ShutdownMTAK failed"
        # log statement

        error_obj = create_step_error(message=msg,
                        details=[],
                        error_type=ing_lib.ErrorType.VENUE_SERVICE_ERROR.value,
                        error_source=ing_lib.ErrorSource.VENUE_SERVICE.value,
                        http_code_at_source=0)

        logger.error(msg, extra= {
            "event": ing_lib.EventName.MTAK_SHUTDOWN.value,
            "data": error_obj
        })

        return return_step_with_error(step, error_obj)
    
    # per ING-3680, previously saved sessions should be cleared.  
    ic.ampcs_session_information.clear()

    # register step data path/session combination
    for entry in results["entries"]:
        ing_lib.register_session(entry['data_path'], entry['session_id'])

    session_id_list = set()
    
    # get list of registered sessions
    for combo in ic.ampcs_session_information:
        session_id = combo["session_id"]
        logger.info(f'session_id: {session_id} type: {type(session_id)}')
        if session_id < 0:
            logger.info(f'ignore negative session_id: {session_id}')
        else:
            session_id_list.add(combo["session_id"])
    
    # Many data paths can point to the same session id. This variable will only append unique session ids to send to MTAK start.
    unique_sessions_list = list(session_id_list)

    # start MTAK with all data paths/sessions. StartMTAK venue service endpoint takes a list of session ids
    msg = 'Starting MTAK for session ids: {}'.format(unique_sessions_list)
    logger.info(msg, extra= {
        "event": ing_lib.EventName.MTAK_START.value
    })
    step_execution = {
        'meta_data': {
            'status': 'RUNNING', 
            'status_message': msg
        },
        'results': results
    }
    report_step_results(step, step_execution, None) 

    try:
        ing_lib.StartMTAK(session=unique_sessions_list, default_cmd_string=default_cmd_string)
    except StepExecutionError as ex:
        msg = "StartMTAK failed"
        # log statement
        logger.error(msg, extra= {
            "event": ing_lib.EventName.MTAK_START.value,
            "data": {
                "message": msg,
                "error_source": ing_lib.ErrorSource.VENUE_SERVICE.value,
                "error_type": ing_lib.ErrorType.VENUE_SERVICE_ERROR.value,
                "http_code_at_source": 400,
                "details": [ex.error_obj]
            }
        })

        return return_step_with_error(step, ex.error_obj)
    except:
        msg = "StartMTAK failed"
        # log statement
        error_obj = create_step_error(message=msg,
                        details=[],
                        error_type=ing_lib.ErrorType.VENUE_SERVICE_ERROR.value,
                        error_source=ing_lib.ErrorSource.VENUE_SERVICE.value,
                        http_code_at_source=0)

        logger.error(msg, extra= {
            "event": ing_lib.EventName.MTAK_START.value,
            "data": error_obj
        })
        # simply raise to preserve the original exception
        return return_step_with_error(step, error_obj)

    # Update the status of the step to PASS
    step["execution"]["meta_data"]["status"] = "PASS"

    step["execution"]["meta_data"]["status_message"] = "" 

    return step

@ing_execution
def run_dummy(step):
    """
    This function is used only for test.
    Note that pid is for debugging and not part of the schema of the step.
    """
    # logger.debug('gds_manual_step.run_dummy()')
    inputs = step['execution_user_input']


    # Pull out the GDSStep definition of the step
    entries = step['execution_user_input']['entries']


    # register step data path/session combination
    for value in entries:
        ing_lib.register_session(value['data_path'],value['session_id'])

    # Populate the query results
    step['execution']['results']['venue_id']=ic.venue_id
    step['execution']['results']['venue_name'] = ic.venue_name
    step['execution']['results']['venue_ampcs_address'] = ic.venue_service_address
    step["execution"]['results']['entries']= entries
    step["execution"]['results']['pid']= os.getpid()

    # Update the status of the step to PASS
    step["execution"]["meta_data"]["status"] = "PASS"

    step["execution"]["meta_data"]["status_message"] = "" 

    return step    
