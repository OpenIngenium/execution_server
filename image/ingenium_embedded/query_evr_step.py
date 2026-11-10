from . import ingenium_library as ing_lib
from . import ingenium_config as ic
from .ingenium_library import ing_execution, get_dict_value_default_none, get_dict_value, create_step_error, return_step_with_error, \
    StepExecutionError, validate_times, EventName
import traceback
from .logging_util import logger
from .verification_lib import verify_query_evr_results
import copy
import json


@ing_execution
def run(step):
    """
    This function implements the QueryEVR step.

    All Ingenium Step Functions only accept the step JSON as both an input and as an output.

    """

    if ic.manual_input_variables.get("step_function_name") and ic.manual_input_variables.get("step_function_name").get('actual_value') == "run_dummy":
        return run_dummy(step)

    results = copy.deepcopy(step["execution_user_input"])
    step['execution']['results'] = results

    # ChillEVRQuery returns a list of JSON objects

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
    
    try:
        translated_start_time, translated_end_time, start_time, end_time = validate_times(results, step.get('step_type'))
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
    
    results.update({
        "venue_id": ic.venue_id,
        "venue_name": ic.venue_name,
        "venue_ampcs_address": ic.venue_service_address,
        "translated_start_time": translated_start_time,
        "translated_end_time": translated_end_time,
        "query_start_time": start_time,
        "query_end_time": end_time,
        "total_count": 0,
        "timeout": results.get("timeout") if results.get("timeout") is not None else ic.evr_chill_timeout,
        "verification_value": results.get("verification_value") if results.get("verification_value") is not None else 0,
        "evr_data": []
    })

    try:
        EVRS=ing_lib.ChillEVRQuery(data_path=data_path,
                                   time_type=get_dict_value_default_none(results, 'time_type'),
                                   evr_name=get_dict_value_default_none(results, 'evr_name'),
                                   evr_id=get_dict_value_default_none(results, 'evr_id'), 
                                   evr_type=get_dict_value_default_none(results, 'evr_type'),
                                   evr_level=get_dict_value_default_none(results, 'evr_level'),
                                   start_time=start_time,
                                   end_time=end_time,
                                   timeout=get_dict_value(results, 'timeout', ic.evr_chill_timeout),
                                   message_filter=get_dict_value_default_none(results, 'message_filter'))
    except StepExecutionError as ex:
        msg = "QueryEVR query to venue failed"
        # log statement
        logger.error(msg, extra = {
            "event": ing_lib.EventName.QUERY_EVRS.value,
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
        msg = "QueryEVR query to venue failed"
        # log statement
        error_obj = create_step_error(message=msg,
                        details=[traceback.format_exc()],
                        error_type=ing_lib.ErrorType.QUERY_ERROR.value,
                        error_source=ing_lib.ErrorSource.VENUE_SERVICE.value,
                        http_code_at_source=400)

        logger.error(msg, extra = {
            "event": ing_lib.EventName.QUERY_EVRS.value,
            "data": error_obj
        })

        return return_step_with_error(step, error_obj)

    evrs_list = []
    if type(EVRS) == list:
        # limit for 25 EVRs.
        for evr in EVRS[-25:]:
            individual_evr = {
                "evr_name": evr["evrName"],
                "session_id": evr["sessionId"],
                "vcid": evr["vcId"],
                "event_id": evr["eventId"],
                "evr_level": evr["evrLevel"],
                "from_sse": evr["fromSSE"],
                "evr_message": evr["evrMessage"],
                "evr_module": evr["evrModule"],
                "sclk": evr["sclk"],
                "ert": evr["ert"],
                "scet": evr["scet"],
                "is_recorded": evr["isRecorded"]
            }
            evrs_list.append(individual_evr)


    # Populate the query results
    results.update({
        "total_count": len(EVRS) if EVRS is not None else 0,
        "evr_data": evrs_list
    })

    verify_query_evr_results(results)

    if results["verification_status"] == "PASS":
        step["execution"]["meta_data"]["status"] = "PASS"
    else:
        step["execution"]["meta_data"]["status"] = "FAIL"

    step["execution"]["meta_data"]["status_message"] = ""

    return step


def run_dummy(step):

    results = copy.deepcopy(step['execution_user_input'])
    results.update({
        'venue_id': ic.venue_id,
        'venue_name': ic.venue_name,
        'venue_ampcs_address': 'dummy_ampcs.example.com',
        "translated_start_time": '',
        "translated_end_time": '',
    })

    evr_data = []
    value_entry = {
                    "evr_name": "SSE_EVR_POWER_ON",
                    "session_id": 3232,
                    "vcid": 0,
                    "event_id": 3487928332,
                    "evr_level": "INFO",
                    "from_sse": True,
                    "evr_message": "SRU_SIM has been powered on",
                    "evr_module": "SSE",
                    "sclk": "527925356",
                    "ert": "2017-032T00:23:03",
                    "scet": "2017-032T00:23:01",
                    "is_recorded": True
                }
    evr_data.append(value_entry)

    results['evr_data'] = evr_data

    step['execution']['results'] = results
    step['execution']['meta_data']['status'] = 'PASS'
    return step
