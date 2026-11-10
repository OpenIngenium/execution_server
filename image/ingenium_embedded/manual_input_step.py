from . import ingenium_config as ic
from . import ingenium_library as ing_lib
from .ingenium_library import ing_execution, create_step_error, return_step_with_error, StepExecutionError, get_dict_value_default_none
from .logging_util import logger
import copy
import traceback
from .verification_lib import Verify


def cast_actual_value(entry):

    if entry["type"] in ["INTEGER"]:
        try:
            entry["actual_value"] = int(entry["actual_value"])
        except:
            msg = "Cannot turn actual value into an integer. User input: {}".format(entry["actual_value"])
            # log statement
            error_obj = create_step_error(message=msg,
                            details=[],
                            error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                            error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)

            logger.error(msg, extra= {
                "event": ing_lib.EventName.USER_INPUT_VALIDATION.value,
                "data": error_obj
            })

            raise StepExecutionError(msg, error_obj)

    elif entry["type"] == "FLOAT":
        try:
            entry['actual_value'] = float(entry["actual_value"])
        except:
            msg = "Cannot turn actual value into a float. User input: {}".format(entry["actual_value"])
            # log statement
            error_obj = create_step_error(message=msg,
                            details=[],
                            error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                            error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)

            logger.error(msg, extra= {
                "event": ing_lib.EventName.USER_INPUT_VALIDATION.value,
                "data": error_obj
            })

            raise StepExecutionError(msg, error_obj)      

    return entry


def record_results(entry, result):
    entry_name = entry["name"]
    ic.manual_input_variables[entry_name] = result

# a special function that used only for tests
def check_error_mode(step):
    for entry in step['execution_user_input']['entries']:
        if entry["name"] == "_TEST_MODE_":
            actual_value = entry.get("actual_value")
            if actual_value == "RUN_ERROR":
                x = 2.0/0.0

@ing_execution
def run(step):

    # Detect a special variable that will trigger a test mode
    check_error_mode(step)

    # initialize results
    results = copy.deepcopy(step['execution_user_input'])
    for entry in results['entries']:
        entry['verification_status'] = 'PENDING'
    step['execution']['results'] = results

    for entry in results["entries"]:
        entry_type = entry["type"]
        entry['actual_value'] = get_dict_value_default_none(entry, 'actual_value')

        try:
            if entry['actual_value'] is not None:
                cast_actual_value(entry)
            ver = Verify.factory(step, entry, value_type=entry_type)
            input_response, actual_value, verification_status = ver.verify()
        except StepExecutionError as ex:
            msg = "Verification failed"
            # log statement
            logger.error(msg, extra = {
                "event": ing_lib.EventName.VERIFY_MANUAL_INPUTS.value,
                "data": {
                    "message": msg,
                    "error_type": ing_lib.ErrorType.VERIFICATION_ERROR.value,
                    "error_source": ing_lib.ErrorSource.EMBEDDED_CODE.value,
                    "http_code_at_source": 0,
                    "details": [str(ex.error_obj)]
                }
            })
            return return_step_with_error(step, ex.error_obj)
        except Exception as ex:
            msg = "Verification failed"
            # log statement
            logger.error(msg, extra = {
                "event": ing_lib.EventName.VERIFY_MANUAL_INPUTS.value,
                "data": {
                    "message": msg,
                    "error_type": ing_lib.ErrorType.VERIFICATION_ERROR.value,
                    "error_source": ing_lib.ErrorSource.EMBEDDED_CODE.value,
                    "http_code_at_source": 0,
                    "details": [traceback.format_exc()]
                }
            })
            # simply raise to preserve the original exception
            return return_step_with_error(step, ex.error_obj)

        # record original actual value from query
        record_results(entry, input_response)


    for entry in results['entries']:
        if entry["verification_status"] == "PASS":
            step["execution"]["meta_data"]["status"] = "PASS"
        else:
            step["execution"]["meta_data"]["status"] = "FAIL"
            break

    step["execution"]["meta_data"]["status_message"] = ""   

    return step
