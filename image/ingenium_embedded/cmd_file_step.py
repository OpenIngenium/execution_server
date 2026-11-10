from . import ingenium_library as ing_lib
from . import ingenium_config as ic
from .ingenium_library import ing_execution, get_dict_value, get_dict_value_default_none, create_step_error, return_step_with_error, StepExecutionError, report_step_results, determine_cmd_failure
import traceback
import copy
from .logging_util import logger
from .verification_lib import BinaryFileVerify


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

    # check to make sure that data path is present and valid
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
        # file_type is a string in core spec but venue server API expects an integer
        # check the string can be converted to int.
        try:
            int(entry.get("file_type"))
        except:

            msg = 'File type: "{}" could not be converted into an integer'.format(entry.get("file_type"))

            error_obj = create_step_error(message=msg,
                            details=[],
                            error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                            error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)
            # log statement
            logger.error(msg, extra = {
                "event": ing_lib.EventName.USER_INPUT_VALIDATION.value,
                "data": error_obj
            })

            return return_step_with_error(step, error_obj)

        # push notice: sending command binary file
        msg = 'Dispatching command binary file from: {}, to: {}'.format(entry["file_path"], entry["onboard_path"])
        logger.info(msg, extra= {
            "event": ing_lib.EventName.DISPATCH_COMMAND_BINARY_FILE.value
        })   
        step_execution = {
            'meta_data': {
                'status': 'RUNNING', 
                'status_message': msg
            },
            'results': results
        }
        report_step_results(step, step_execution, None)   

        # logic if user input "verify" is True
        if entry["verify"] == True:
            try:
                binaryfile = BinaryFileVerify(entry=entry, data_path=data_path, step=step)
                binaryfile.binary_file_verification()
            except StepExecutionError as ex:
                msg = "Error executing command binary file step"
                logger.error(msg, extra = {
                    "event": ing_lib.EventName.DISPATCH_COMMAND_BINARY_FILE.value,
                    "data": {
                        "message": msg,
                        "error_type": ing_lib.ErrorType.DISPATCH_ERROR.value,
                        "error_source": ing_lib.ErrorSource.VENUE_SERVICE.value,
                        "http_code_at_source": 400,
                        "details": [str(ex.error_obj)]
                    }
                })
                return return_step_with_error(step, ex.error_obj)
        else:
            try:
                binaryfile_cmd = ing_lib.CommandBinaryFile(data_path=results["data_path"], source_file_path=entry["file_path"],
                                                           target_file_path=entry["onboard_path"], file_type=entry["file_type"],
                                                           string_selection=entry.get('string_selection', 'DEFAULT'), overwrite=get_dict_value_default_none(entry, "overwrite"), 
                                                           timeout=get_dict_value(entry, "timeout", ic.cmd_timeout))
            except StepExecutionError as ex:
                msg = "CommandBinaryFile query to venue failed"
                # log statement
                logger.error(msg, extra = {
                    "event": ing_lib.EventName.DISPATCH_COMMAND_BINARY_FILE.value,
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
                msg = "CommandBinaryFile query to venue failed"

                error_obj = create_step_error(message=msg,
                                details=[traceback.format_exc()],
                                error_type=ing_lib.ErrorType.DISPATCH_ERROR.value,
                                error_source=ing_lib.ErrorSource.VENUE_SERVICE.value,
                                http_code_at_source=400)

                # log statement
                logger.error(msg, extra = {
                    "event": ing_lib.EventName.DISPATCH_COMMAND_BINARY_FILE.value,
                    "data": error_obj
                })


                return return_step_with_error(step, error_obj)
            
            entry.update({
                "radiated": True if "dispatchTime" in binaryfile_cmd else False,
                "radiated_time": binaryfile_cmd["dispatchTime"] if "dispatchTime" in binaryfile_cmd else None,
                "verified": False,
                "verified_time": ""
            })

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

    print("cmd_file_step.run_dummy()")
    queries = copy.deepcopy(step['execution_user_input'])

    outputs = []

    for query in queries["entries"]:

        cmdfile_data = {
            "file_type": "0",
            "timeout": 10,
            "file_path": "/home/directory/path.sh",
            "onboard_path": "/target/directory/setup.sh",
            "overwrite": True,
            "verify": True,
            "radiated": True,
            "radiated_time": "2017-032T00:23:03",
            "verified": True,
            "verified_time": "2017-032T00:22:50"
        }

        outputs.append(cmdfile_data)

    results = {
        "entries": outputs
    }

    step['execution']['results'] = results
    step['execution']['meta_data']['status'] = 'PASS'
    return step
