from . import ingenium_library as ing_lib
from . import ingenium_config as ic
from .ingenium_library import ing_execution, get_dict_value, create_step_error, return_step_with_error, StepExecutionError, report_step_results, determine_cmd_failure
import traceback
import copy
from .logging_util import logger

@ing_execution
def run(step):


    if ic.manual_input_variables.get("step_function_name") and ic.manual_input_variables.get("step_function_name").get('actual_value') == "run_dummy":
        return run_dummy(step)

    input_copy = copy.deepcopy(step["execution_user_input"])
    outputs = []

    for entry in input_copy["entries"]:

        data_path=input_copy.get('data_path')
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

        try:
            # push notice: sending command SCMF
            command_dispatch_msg = {'meta_data': {'status': 'RUNNING', 'status_message': 'Sending command SCMF'}}
            # log statement
            msg = 'Sending command SCMF'
            logger.info(msg, extra= {
                "event": ing_lib.EventName.DISPATCH_COMMAND_SCMF.value
            })   
            report_step_results(step, command_dispatch_msg, None)   
            # for the time being disable_check will be set to True for all command scmf.
            scmf_cmd = ing_lib.CommandSCMF(data_path=data_path, file_path=entry["file_path"], disable_checks=True, timeout=get_dict_value(entry, "timeout", ic.cmd_timeout))

        except StepExecutionError as ex:
            msg = "CommandSCMF query to venue failed"
            # log statement
            logger.error(msg, extra = {
                "event": ing_lib.EventName.DISPATCH_COMMAND_SCMF.value,
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
            msg = "CommandSCMF query to venue failed"
            # log statement
            error_obj = create_step_error(message=msg,
                            details=[traceback.format_exc()],
                            error_type=ing_lib.ErrorType.DISPATCH_ERROR.value,
                            error_source=ing_lib.ErrorSource.VENUE_SERVICE.value,
                            http_code_at_source=400)

            logger.error(msg, extra = {
                "event": ing_lib.EventName.DISPATCH_COMMAND_SCMF.value,
                "data": error_obj
            })

            return return_step_with_error(step, error_obj)

        scmf_object_addition = {
            "scmf_name": entry["file_path"].split("/")[-1] if "file_path" in entry else "",
            "radiated": True if "dispatchTime" in scmf_cmd else False,
            "radiated_time": scmf_cmd["dispatchTime"] if "dispatchTime" in scmf_cmd else "",
            "verified": False,
            "verified_time": ""        
        }

        entry.update(scmf_object_addition)
        outputs.append(entry)

        is_failure = determine_cmd_failure(step.get("step_type"), entry.get("verify"), scmf_object_addition)

        if is_failure:
            break

    output_object = {
        "data_path": input_copy["data_path"],
        "entries": outputs
    }

    step["execution"]["results"] = output_object

    step["execution"]["meta_data"]["status"] = "PASS"
    for entry in output_object["entries"]:
        if not entry["radiated"]:
            step["execution"]["meta_data"]["status"] = "FAIL"
            break

    step["execution"]["meta_data"]["status_message"] = ""
    return step



def run_dummy(step):

    print('cmd_scmf_step.run_dummy()')
    queries = queries = copy.deepcopy(step['execution_user_input'])

    outputs = []

    for query in queries["entries"]:

        cmdscmf_data = {
            "file_type": "0",
            "timeout": 10,
            "file_path": "/temp/directory/setup.sh",
            "verify": True,
            "scmf_name": "mpcs_wsts_1",
            "radiated": True,
            "radiated_time": "2017-032T00:23:03",
            "verified": True,
            "verified_time": "2017-032T00:22:50"
        }

        outputs.append(cmdscmf_data)

    results = {
        "entries": outputs
    }

    step['execution']['results'] = results
    step['execution']['meta_data']['status'] = 'PASS'
    return step
