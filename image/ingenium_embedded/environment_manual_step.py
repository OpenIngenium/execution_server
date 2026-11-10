from . import ingenium_config as ic
from . import ingenium_library as ing_lib
from .ingenium_library import ing_execution, create_step_error, return_step_with_error, StepExecutionError, get_dict_value_default_none, report_step_results
from .logging_util import logger
import copy
from .verification_lib import Verify


@ing_execution
def run(step):
    results = copy.deepcopy(step['execution_user_input'])

    # initialize results
    step['execution']['results'] = results

    if results.get("temperature") is not None:
        results["temperature"]["verification_status"] = 'PENDING'
    if results.get("humidity") is not None:
        results["humidity"]["verification_status"] = 'PENDING'

    if results.get("temperature") is not None:
        temp_actual_value = get_dict_value_default_none(results["temperature"], "actual_value")
        try:
            if temp_actual_value is not None:
                temp_actual_value = float(temp_actual_value)
        except:
            msg = "Temperature must be type 'integer' or 'float'"
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

            return return_step_with_error(step, error_obj)

        try:
            ver = Verify.factory(step, results["temperature"], environment_type="temperature")
            # Note verify() will set verification_status in "results"
            ver.verify()
        except StepExecutionError as ex:
            msg = "Verification failed"
            # log statement
            logger.error(msg, extra = {
                "event": ing_lib.EventName.VERIFY_ENVIRONMENT_TEMP.value,
                "data": {
                    "message": msg,
                    "error_type": ing_lib.ErrorType.VERIFICATION_ERROR.value,
                    "error_source": ing_lib.ErrorSource.EMBEDDED_CODE.value,
                    "http_code_at_source": 0,
                    "details": [str(ex.error_obj)]
                }
            })
            return return_step_with_error(step, ex.error_obj)

        ic.environment_step_variables["temperature"] = {
            "actual_value": temp_actual_value
        }


    if results.get("humidity") is not None:
        humidity_actual_value = get_dict_value_default_none(results["humidity"], "actual_value")

        try:
            if humidity_actual_value is not None:
                humidity_actual_value = float(humidity_actual_value)
        except:
            msg = "Humidity must be type 'integer' or 'float'"
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

            return return_step_with_error(step, error_obj)

        try:
            ver = Verify.factory(step, results["humidity"], environment_type="humidity")
            # Note verify() will set verification_status in "results"
            ver.verify()
        except StepExecutionError as ex:
            msg = "Verification failed"
            # log statement
            logger.error(msg, extra = {
                "event": ing_lib.EventName.VERIFY_ENVIRONMENT_HUMIDITY.value,
                "data": {
                    "message": msg,
                    "error_type": ing_lib.ErrorType.VERIFICATION_ERROR.value,
                    "error_source": ing_lib.ErrorSource.EMBEDDED_CODE.value,
                    "http_code_at_source": 0,
                    "details": [str(ex.error_obj)]
                }
            })
            return return_step_with_error(step, ex.error_obj)

        ic.environment_step_variables["humidity"] = {
            "actual_value": humidity_actual_value
        }

    if results.get("temperature") and results["temperature"]["verification_status"] == "PASS" and \
        results.get("humidity") and results["humidity"]["verification_status"] == "PASS":
        step["execution"]["meta_data"]["status"] = "PASS"
    else:
        step["execution"]["meta_data"]["status"] = "FAIL"

    step["execution"]["meta_data"]["status_message"] = ""

    return step
