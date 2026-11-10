from . import ingenium_library as ing_lib
from . import ingenium_config as ic
from .ingenium_library import ing_execution, get_dict_value_default_none, get_dict_value, create_step_error, return_step_with_error, StepExecutionError, \
    validate_times, EventName
import traceback
from .logging_util import logger
import copy
import json

@ing_execution
def run(step):
    """
    This function implements the GraphEHA step.

    All Ingenium Step Functions only accept the step JSON as both an input and as an output.

    """

    if ic.manual_input_variables.get("step_function_name") and ic.manual_input_variables.get("step_function_name").get('actual_value') == "run_dummy":
        return run_dummy(step)

    # Pull out the GraphEHA definition of the step
    step_input = copy.deepcopy(step["execution_user_input"])

    data_path=step_input.get('data_path')
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

    if step_input.get("channel_type") is not None:
        if type(step_input.get("channel_type")) is not str:
            
            msg = 'Channel type must be a string'
            # log statement
            error_obj = create_step_error(message=msg,
                            details=[],
                            error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                            error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)

            logger.error(msg, extra = {
                "event": ing_lib.EventName.USER_INPUT_VALIDATION.value,
                "data": error_obj
            })

            return return_step_with_error(step, error_obj)

    try:
        translated_start_time, translated_end_time, start_time, end_time = validate_times(step_input, step.get('step_type'))
    except StepExecutionError as ex:
        msg = "Time calculation error - {}.".format(json.dumps(ex.error_obj))

        error_obj = create_step_error(message=msg,
                        details=[],
                        error_type=ing_lib.ErrorType.TIME_VALIDATION_ERROR.value,
                        error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                        http_code_at_source=0)

        logger.error(msg, extra = {
            "event": EventName.TIME_VALIDATION.value,
            "data": error_obj
        })

        return return_step_with_error(step, ex.error_obj)

    # ChillEHAQuery returns a list of JSON objects
    try:
        channels=ing_lib.ChillEHAQuery(channel_id=get_dict_value_default_none(step_input, 'channel_id'),
                                       start_time=start_time,
                                       end_time=end_time,
                                       time_type=get_dict_value_default_none(step_input, 'time_type'),
                                       timeout=get_dict_value(step_input, 'timeout', ic.eha_chill_timeout),
                                       channel_type=get_dict_value_default_none(step_input, 'channel_type'),
                                       data_path=step_input['data_path'])
    except StepExecutionError as ex:
        msg = "GraphEHA query to venue failed"
        # log statement
        logger.error(msg, extra = {
            "event": ing_lib.EventName.QUERY_EHAS.value,
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
        msg = "GraphEHA query to venue failed"
        # log statement
        error_obj = create_step_error(message=msg,
                        details=[traceback.format_exc()],
                        error_type=ing_lib.ErrorType.QUERY_ERROR.value,
                        error_source=ing_lib.ErrorSource.VENUE_SERVICE.value,
                        http_code_at_source=400)

        logger.error(msg, extra = {
            "event": ing_lib.EventName.QUERY_EHAS.value,
            "data": error_obj
        })

        return return_step_with_error(step, error_obj)

    channel_data = []

    if type(channels) == list:

        dn_eu = step_input["dn_eu"].lower()

        for channel in channels:

            channel_object = {
                "time": channel["ert"],
                "value": channel[dn_eu]
            }

            channel_data.append(channel_object)


    # Populate the query results
    results_object = {
        "venue_id": ic.venue_id,
        "venue_name": ic.venue_name,
        "venue_ampcs_address": ic.venue_service_address,
        "translated_start_time": translated_start_time,
        "translated_end_time": translated_end_time,
        "query_start_time": start_time,
        "query_end_time": end_time,
        "channel_id": step_input.get("channel_id"),
        "start_time": step_input.get("start_time"),
        "end_time": step_input.get("end_time"),
        "duration": str(step_input.get("duration")),
        "time_type": step_input.get("time_type"),
        "timeout": step_input.get("timeout") if step_input.get("timeout") is not None else ic.eha_chill_timeout,
        "channel_type": step_input.get("channel_type"),
        "dn_eu": step_input.get("dn_eu"),
        "data_path": step_input.get("data_path"),
        "total_count": len(channels) if type(channels) == list else 0,
        "channel_data": channel_data
    }

    # insert results_object into step json
    step["execution"]["results"] = results_object

    # Update the status of the step to PASS
    if results_object["channel_data"]:
        step["execution"]["meta_data"]["status"] = "PASS"  
    else:
        step["execution"]["meta_data"]["status"] = "FAIL"

    step["execution"]["meta_data"]["status_message"] = "" 

    return step


def run_dummy(step):

    step_input = step['execution_user_input']

    results = copy.deepcopy(step_input)

    results.update({
        'venue_id': ic.venue_id,
        'venue_name': ic.venue_name,
        'venue_ampcs_address': ic.venue_service_address,
        "translated_start_time": '',
        "translated_end_time": '',
        "query_start_time": '',
        "query_end_time": ''
    })

    channel_data = []
    channel_data.append({"time": "2017-032T00:23:03", "value": "34.5"})
    channel_data.append({"time": "2017-032T00:23:07", "value": "34.9"})

    results['channel_data'] = channel_data

    step['execution']['results'] = results
    step['execution']['meta_data']['status'] = 'PASS'
    return step
