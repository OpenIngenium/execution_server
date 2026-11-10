from . import ingenium_library as ing_lib
from .ingenium_library import ing_execution,get_dict_value, create_step_error, return_step_with_error, StepExecutionError, report_step_results, determine_cmd_failure
from . import ingenium_config as ic
import traceback
import copy
from .logging_util import logger

@ing_execution
def run(step):

    if ic.manual_input_variables.get("step_function_name") and ic.manual_input_variables.get("step_function_name").get('actual_value') == "run_dummy":
        return run_dummy(step)

    results = copy.deepcopy(step["execution_user_input"])
    for entry in results["entries"]:
        entry['radiated'] = False
        entry['radiated_time'] = ''

    step["execution"]["results"] = results

    data_path = results.get('data_path')
    if not data_path:
        msg = "Data path was not provided"
        # log statement
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
        msg = 'Dispatching SSE command: {}'.format(entry["cmd_string"])
        logger.info(msg, extra = {
            "event": ing_lib.EventName.DISPATCH_COMMAND_SSE.value
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
            sse_cmd = ing_lib.CommandSSE(data_path=data_path, command_string=entry["cmd_string"], timeout=get_dict_value(entry, "timeout", ic.cmd_timeout))

        except StepExecutionError as ex:
            msg = "CommandSSE query to venue failed"
            # log statement
            logger.error(msg, extra = {
                "event": ing_lib.EventName.DISPATCH_COMMAND_SSE.value,
                "data": {
                    "message": msg,
                    "error_type": ing_lib.ErrorType.DISPATCH_ERROR.value,
                    "error_source": ing_lib.ErrorSource.VENUE_SERVICE.value,
                    "http_code_at_source": 400,
                    "details": [str(ex.error_obj)]
                }
            })

            return return_step_with_error(step, ex.error_obj)

        except Exception as ex:
            msg = "CommandSSE query to venue failed"
            # log statement
            error_obj = create_step_error(message=msg,
                            details=[traceback.format_exc()],
                            error_type=ing_lib.ErrorType.DISPATCH_ERROR.value,
                            error_source=ing_lib.ErrorSource.VENUE_SERVICE.value,
                            http_code_at_source=400)

            logger.error(msg, extra = {
                "event": ing_lib.EventName.DISPATCH_COMMAND_SSE.value,
                "data": error_obj
            })

            return return_step_with_error(step, error_obj)

        sse_cmd_object_addition = {
            "radiated": True if "dispatchTime" in sse_cmd else False,
            "radiated_time": sse_cmd["dispatchTime"] if "dispatchTime" in sse_cmd else None
        }

        entry.update(sse_cmd_object_addition)

        is_failure = determine_cmd_failure(step.get("step_type"), False, sse_cmd_object_addition)

        if is_failure:
            break


    step["execution"]["meta_data"]["status"] = "PASS"

    for entry in results["entries"]:
        if not entry["radiated"]:
            step["execution"]["meta_data"]["status"] = "FAIL"
            break

    step["execution"]["meta_data"]["status_message"] = ""

    return step



def run_dummy(step):

    print('cmd_sse_step.run_dummy()')
    queries = queries = copy.deepcopy(step['execution_user_input'])

    outputs = []

    for query in queries["entries"]:

        cmdscmf_data = {
            "timeout": 10,
            "cmd_string": "flight 123 42 1231",
            "radiated": True,
            "radiated_time": "2017-032T00:23:03"
        }

        outputs.append(cmdscmf_data)

    results = {
        "entries": outputs
    }

    step['execution']['results'] = results
    step['execution']['meta_data']['status'] = 'PASS'
    return step
