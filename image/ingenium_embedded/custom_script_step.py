from . import ingenium_config as ic
from . import ingenium_library as ing_lib
from .ingenium_library import CustomScriptResponse, get_dict_value, refresh_venue_tokens, ing_execution, create_step_error, return_step_with_error, StepExecutionError, get_dict_value_default_none, report_step_results, EventName
from .logging_util import logger
import copy
import traceback
import json
import time


@ing_execution
def run(step):
    execution_id = step.get('execution_id')
    elem_id = step.get('elem_id')
    number = step.get('number')
    # process Core input
    step_input = copy.deepcopy(step["execution_user_input"])
    custom_script_response = CustomScriptResponse(step_input)
    
    # initialize results so that input values are available when the step errors or is canceled. 
    step['execution']['results'] = custom_script_response.return_intermediate_response()

    timeout = get_dict_value(step_input, "timeout", ic.custom_script_timeout)

    # USER INPUT VALIDATION: script name exists
    if get_dict_value_default_none(step_input, "script_name") is None:
        msg = "Script name must be present"

        error_obj = create_step_error(message=msg,
                        details=[],
                        error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                        error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                        http_code_at_source=0)
      

        logger.error(msg, extra = {
            "event": EventName.USER_INPUT_VALIDATION.value,
            "data": error_obj
        })

        return return_step_with_error(step, error_obj)

    # USER INPUT VALIDATION: hash exists
    if get_dict_value_default_none(step_input, "hash") is None:
        msg = "Hash must be present"

        error_obj = create_step_error(message=msg,
                        details=[],
                        error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                        error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                        http_code_at_source=0)

        logger.error(msg, extra = {
            "event": EventName.USER_INPUT_VALIDATION.value,
            "data": error_obj
        })

        return return_step_with_error(step, error_obj)

    # USER INPUT VALIDATION: script path exists 
    if get_dict_value_default_none(step_input, "script_path") is None:
        msg = "Script path must be present"

        error_obj = create_step_error(message=msg,
                        details=[],
                        error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                        error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                        http_code_at_source=0)

        logger.error(msg, extra = {
            "event": EventName.USER_INPUT_VALIDATION.value,
            "data": error_obj
        })

        return return_step_with_error(step, error_obj)

    # initiate custom script start 
    try:
        start_result = ing_lib.start_custom_script(step_input=step_input)
    except StepExecutionError as ex:
        msg = "Start Custom Script query to venue failed"
        # log statement
        logger.error(msg, extra = {
            "event": ing_lib.EventName.START_CUSTOM_SCRIPT.value,
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
        msg = "Start Custom Script query to venue failed"

        error_obj = create_step_error(message=msg,
                        details=[traceback.format_exc()],
                        error_type=ing_lib.ErrorType.QUERY_ERROR.value,
                        error_source=ing_lib.ErrorSource.VENUE_SERVICE.value,
                        http_code_at_source=400)

        # log statement
        logger.error(msg, extra = {
            "event": ing_lib.EventName.START_CUSTOM_SCRIPT.value,
            "data": error_obj
        })

        return return_step_with_error(step, error_obj)

    # "script_status" is intially set to "PENDING"
    script_status = "PENDING"

    # scriptRunId is the "session id" that is returned from the custom script start API call. 
    # This id is used to query for status, and if need be to halt the custom script
    scriptRunId = start_result.get("scriptRunId")

    try:
        ing_lib.store_custom_script_session_id(execution_id, scriptRunId)
    except Exception as ex:
        logger.warning(f'Failed to cache custom script session id. execution_id: {execution_id} number: {number} elem_id: {elem_id}')    
    
    poll_msg = "Checking custom script status"

    logger.info(poll_msg, extra = {
        "event": ing_lib.EventName.CHECK_CUSTOM_SCRIPT_STATUS.value
    })

    poll_script_msg = {
        "meta_data": {
            "status": "RUNNING",
            "status_message": poll_msg
        }
    }

    report_step_results(step, poll_script_msg, None)

    # POLL for status
    time_started = time.time()
    time_elapsed = 0.0

    # Initialize here outside the polling loop so that we can use the last status available after the loop is done
    # in the case where status query was not successful and timeout happened.
    script_status_info = {}
        
    while time_elapsed < timeout and script_status == "PENDING":
        refresh_venue_tokens()

        status_response = None

        try:
            status_response = ing_lib.get_script_status(scriptRunId)
        except Exception as ex:
            msg = "Custom Script status query to venue failed."

            error_obj = create_step_error(message=msg,
                            details=[traceback.format_exc()],
                            error_type=ing_lib.ErrorType.QUERY_ERROR.value,
                            error_source=ing_lib.ErrorSource.VENUE_SERVICE.value,
                            http_code_at_source=0)

            # log statement
            logger.warning(msg, extra = {
                "event": ing_lib.EventName.CUSTOM_SCRIPT_STATUS.value,
                "data": error_obj
            })

        if status_response is not None:
            if status_response.status_code == 200:
                script_status_info = json.loads(status_response.text)
                # send intermediate results to execution monitor
                # logger.debug("SCRIPT STATUS RETURN OBJECT: {}".format(script_status_info))
                custom_script_response.update_outputs_with_results(script_status_info)
                msg = "Custom Script status: {}".format(script_status_info.get("custom_script_status"))
                logger.debug(msg, extra = {
                    "event": ing_lib.EventName.CUSTOM_SCRIPT_STATUS.value
                })

                logfile_lines = script_status_info.get("logfile_lines")
                intermediate_results_msg = {
                    'meta_data': {
                        'status': 'RUNNING',
                        'status_message': '\n'.join(logfile_lines) if isinstance(logfile_lines, list) else str(logfile_lines)
                    },
                    'results': custom_script_response.return_intermediate_response()
                }

                # logger.info("intermediate results: {}".format(intermediate_results_msg))

                report_step_results(step, intermediate_results_msg, None)  

                # set script status for next loop
                script_status = script_status_info.get("custom_script_status")
            else:
                msg = "Failed to get the status of custom script."
                error_obj = create_step_error(message=msg,
                                details=[status_response.text],
                                error_type=ing_lib.ErrorType.QUERY_ERROR.value,
                                error_source=ing_lib.ErrorSource.VENUE_SERVICE.value,
                                http_code_at_source=status_response.status_code)

                # log statement
                logger.warning(msg, extra = {
                    "event": ing_lib.EventName.CUSTOM_SCRIPT_STATUS.value,
                    "data": error_obj
                })

        # Always sleep and update timer
        time.sleep(1)
        time_elapsed = time.time() - time_started        


    # Check results
    result_script_status = custom_script_response.return_script_status()
    time_out_flag = not (time_elapsed < timeout)
    logger.info("Custom script has completed. path: {} status: {} time_out_flag: {}".format(step_input.get("script_path"), result_script_status, time_out_flag), extra={
        "event": ing_lib.EventName.CUSTOM_SCRIPT_EXECUTION_COMPLETE.value
    })
    

    # Now custom script is completed. Reset custom_script_session_id in cache.
    # This is done to skip calling venue server to kill custom script process 
    # when no custom script is running.
    try:
        ing_lib.store_custom_script_session_id(execution_id, '')
    except Exception as ex:
        logger.warning(f'Failed to reset custom script session id. execution_id: {execution_id} number: {number} elem_id: {elem_id}')  

    # get logfile url
    logfile_url = script_status_info.get("logfile_url")
    logger.info("Logfile url: {}".format(logfile_url))
    if logfile_url is None:
        logger.warning("Logfile url was not found in status response object: {}".format(script_status_info))


    logfile_lines = script_status_info.get("logfile_lines")
    details = logfile_lines if isinstance(logfile_lines, list) else [str(logfile_lines)]
    
    output_json = {}
    fileserver_logfile_url = ''
    if logfile_url is not None:
        logger.info("Retrieving custom script logs tarball from GDS host...")
        try:
            fileserver_logfile_url, output_json = ing_lib.process_cs_files(logfile_url, scriptRunId, custom_script_response)
        except StepExecutionError as ex:
            msg = "There was an error retrieving the custom script logs tarball"
            # log statement
            logger.error(msg, extra = {
                "event": ing_lib.EventName.CUSTOM_SCRIPT_STATUS.value,
                "data": {
                    "message": msg,
                    "error_type": ing_lib.ErrorType.QUERY_ERROR.value,
                    "error_source": ing_lib.ErrorSource.VENUE_SERVICE.value,
                    "http_code_at_source": 400,
                    "details": [str(ex.error_obj)]
                }
            })
            return return_step_with_error(step, ex.error_obj)
        
    # update states of the execution
    states = output_json.get('states', {})
    for var_name, var_value in states.get('variables', {}).items():
        logger.debug(f'variables var_name: {var_name} var_value: {var_value}')
        ic.variables[var_name] = var_value
    for var_name, var_value in states.get('channel_variables', {}).items():
        logger.debug(f'channel_variables var_name: {var_name} var_value: {var_value}')
        ic.channel_variables[var_name] = var_value
    for var_name, var_value in states.get('manual_input_variables', {}).items():
        logger.debug(f'manual_input_variables var_name: {var_name} var_value: {var_value}')
        ic.manual_input_variables[var_name] = var_value
    for var_name, var_value in states.get('mil_1553_variables', {}).items():
        logger.debug(f'mil_1553_variables var_name: {var_name} var_value: {var_value}')
        ic.mil_1553_variables[var_name] = var_value

    # In the case of time out or pending, we want to kill all processes.
    # ERROR does not need any manual halting. All processes kill themselves when the subprocess dies.
    # Note: This needs to be done after downloading log files because halt will remove the 
    # current run id in venue server.
    if time_out_flag or (result_script_status not in ["PASS", "FAIL", "ERROR"]):
        try:
            ing_lib.halt_script(scriptRunId)    
        except Exception as ex:
            # log the error and continue so that results can be returned  
            msg = f'Failed when halting a script. execution_id: {execution_id} number: {number} elem_id: {elem_id}'
            logger.error(msg, extra = {
                "event": ing_lib.EventName.CUSTOM_SCRIPT_STATUS.value,
                "data": {
                    "message": msg,
                    "error_type": ing_lib.ErrorType.QUERY_ERROR.value,
                    "error_source": ing_lib.ErrorSource.VENUE_SERVICE.value,
                    "http_code_at_source": 0,
                    "details": [str(ex.error_obj)]
                }
            })      

    # update response object with logfile_local_path
    custom_script_response.update_logfile_url(fileserver_logfile_url)
    step["execution"]["results"] = custom_script_response.return_intermediate_response()

    if result_script_status == "ERROR":
        err_message = "There was an error executing custom script: {}".format(step_input.get("script_path"))
        error_obj = create_step_error(message=err_message,
                        details=details,
                        error_type=ing_lib.ErrorType.STEP_ERROR.value,
                        error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                        http_code_at_source=0)

        # log script error 
        logger.error(err_message, extra = {
            "event": ing_lib.EventName.CHECK_CUSTOM_SCRIPT_STATUS.value,
            "data": error_obj       
        })
        step['execution']['meta_data']['error'] = error_obj
    elif time_out_flag:
        # return step error if timeout and not in status "PASS", "FAIL", "ERROR" meaning
        # that the script is still running but time limit was reached.
        err_message = "Timeout reached"         
        error_obj = create_step_error(message=err_message,
                        details=details,
                        error_type=ing_lib.ErrorType.TIMEOUT.value,
                        error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                        http_code_at_source=0)

        # log timeout 
        logger.error("Timeout reached.", extra = {
            "event": ing_lib.EventName.CHECK_CUSTOM_SCRIPT_STATUS.value,
            "data": error_obj       
        })
        step['execution']['meta_data']['error'] = error_obj

    if step['execution']['results']['custom_script_status'] == "PASS":
        step['execution']['meta_data']['status'] = step['execution']['results']['custom_script_status']
    else:
        step['execution']['meta_data']['status'] = 'FAIL'

    # Keep the status_message, which may be useful for trouble shooting.
    step['execution']['meta_data']['status_message'] = '\n'.join(details)

    return step
