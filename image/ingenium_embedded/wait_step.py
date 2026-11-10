from . import ingenium_config as ic
from . import ingenium_library as ing_lib
from .ingenium_library import ing_execution, create_step_error, return_step_with_error, StepExecutionError, convert_time, report_step_results
from .logging_util import logger
import copy
from datetime import datetime
import time

@ing_execution
def run(step):

    if ic.variables.get('step_function_name') == 'run_dummy':
        return run_dummy(step)

    # initialize results
    results = copy.deepcopy(step['execution_user_input'])
    step['execution']['results'] = results

    duration_seconds = 0

    if results["wait_type"] == "DURATION":

        # "time_entry" can either by an integer or float. Casting into float is inclusive of integer casting.
        try:
            duration_seconds = float(results["time_value"])
        except ValueError:
            msg = "Cannot convert duration into seconds. Duration input - {}".format(results["time_value"])
            # log statement
            error_obj = create_step_error(message=msg,
                            details=[],
                            error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                            error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)

            logger.error(msg, {
                "event": ing_lib.EventName.USER_INPUT_VALIDATION.value ,
                "data": error_obj
            })


            return return_step_with_error(step, error_obj)


    # strategy: calculate the timedelta between current time and until time. Convert to seconds and use sleep function to handle wait.
    elif results["wait_type"] == "UNTIL":

        now_time = datetime.utcnow()

        # attempt to convert time value to standard utc datetime.
        try:
            until_time = convert_time(results["time_value"])
        except StepExecutionError as ex:
            msg = "Cannot convert time value into a datetime. Until time input - {}".format(results["time_value"])
            # log statement
            error_obj = create_step_error(message=msg,
                            details=[str(ex)],
                            error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                            error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)

            logger.error(msg, {
                "event": ing_lib.EventName.USER_INPUT_VALIDATION.value,
                "data": error_obj
            })

            return return_step_with_error(step, error_obj)

        # check if until time comes after now time
        if now_time > until_time:
            msg = "Until time is earlier than current time. Until time - {}".format(until_time)
            # log statement
            error_obj = create_step_error(message=msg,
                            details=[],
                            error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                            error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)

            logger.error(msg, {
                "event": ing_lib.EventName.USER_INPUT_VALIDATION.value,
                "data": error_obj
            })

            return return_step_with_error(step, error_obj)

        # execute the wait
        duration_seconds = (until_time - now_time).total_seconds()

    # calculate report interval. Interval should be no less than 10 seconds to avoid too frequent calls to Core.
    report_interval_seconds = max(duration_seconds/100, 10)

    seconds_left = duration_seconds
    while seconds_left > 0:
        # send status update to Core
        step_execution = {
            'results': results,
            'meta_data': {'status': 'RUNNING', 'status_message': '{} seconds left'.format(seconds_left)}
        }
        # log statement
        logger.info("{} seconds left".format(seconds_left), extra= {
            "event": ing_lib.EventName.WAIT_INTERMEDIATE_RESULT.value
        })
        report_step_results(step, step_execution, None)        
        wait_seconds = min(seconds_left, report_interval_seconds)
        time.sleep(wait_seconds)
        seconds_left = seconds_left - wait_seconds

    step["execution"]["meta_data"]["status"] = "PASS"

    # the final results will be received by "ing_execution" decorator and be reported back to Core
    step["execution"]["meta_data"]["status_message"] = ""

    return step

def run_dummy(step):

    results = copy.deepcopy(step["execution_user_input"])
    step["execution"]["results"] = results
    step["execution"]["meta_data"]["status"] = "PASS"
    return step
