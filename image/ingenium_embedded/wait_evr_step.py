from . import ingenium_library as ing_lib
from . import ingenium_config as ic
from .ingenium_library import ing_execution, get_dict_value_default_none, get_dict_value, create_step_error, return_step_with_error, StepExecutionError, \
    validate_times, report_step_results, EvrResponse, refresh_venue_tokens, EventName, convert_time
import traceback
import copy
import time
from datetime import datetime, timedelta
from .logging_util import logger
import math


@ing_execution
def run(step):

    if ic.manual_input_variables.get("step_function_name") and ic.manual_input_variables.get("step_function_name").get('actual_value') == "run_dummy":
        return run_dummy(step)

    step_input = copy.deepcopy(step["execution_user_input"])

    timeout_input = get_dict_value(step_input, "timeout", ic.evr_rt_timeout)
    timeout_copy = timeout_input

    try:
        translated_start_time, translated_end_time, start_time, end_time = validate_times(step_input, step.get('step_type'))
    except StepExecutionError as ex:
        msg = "Time calculation error"

        # log statement
        logger.error(msg, extra = {
            "event": ing_lib.EventName.USER_INPUT_VALIDATION.value,
            "data": {
                "message": msg,
                "error_type": ing_lib.ErrorType.USER_INPUT_ERROR.value,
                "error_source": ing_lib.ErrorSource.EMBEDDED_CODE.value,
                "http_code_at_source": 0
            }
        })

        return return_step_with_error(step, ex.error_obj)

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

    # initialize evr response object
    evr_response_object = EvrResponse(step_input['entries'], translated_start_time, translated_end_time, start_time, end_time)
    # initialize results so that input values are available when the step errors or is canceled.
    step['execution']['results'] = evr_response_object.return_intermediate_response()

    # log entries
    entries_msg = "Input entries: {}".format(step_input["entries"])
    logger.info(entries_msg, extra = {
        "event": ing_lib.EventName.QUERY_EVRS.value
    })

    for index, entry in enumerate(step['execution']['results']['entries']):
        query_counter = 0
        entry_verified = False
        ran_once = False
        passed_query_window = False
        verification_condition = entry.get("verification_condition")        
        evr_type = entry.get("evr_type")
        entry["verification_status"] = "PENDING"
        display_timeout = timeout_copy

        while (not ran_once) or ((timeout_copy > 0) and (not passed_query_window) and (not entry_verified)):
            
            refresh_venue_tokens()
            ran_once = True
            timer_start = time.time()

            if timeout_copy <= 0:
                search_msg = 'Searching for EVR: {} once'.format(entry["evr_name"])
            else:
                search_msg = 'Searching for EVR: {} - timeout remaining {} seconds'.format(entry["evr_name"], display_timeout)

            logger.info(search_msg, extra = {
                "event": ing_lib.EventName.QUERY_EVRS.value
            })

            # push notice: search for EVR telemetry
            search_evr_msg = {
                'meta_data': {
                    'status': 'RUNNING',
                    'status_message': search_msg
                }
            }
            report_step_results(step, search_evr_msg, None)

            query_counter += 1
            total_count = 0

            try:                        
                if (query_counter % ic.chill_query_frequency) > 0:
                    # Note that RealtimeEVR (and venue server) does not support evr_type input.
                    # The results may include any of FSW_RECORDED, FSW_REALTIME, or SSE
                    # as indicated by boolean flags of isRecorded and fromSSE.
                    evrs = ing_lib.RealtimeEVR(data_path=step_input["data_path"],
                                                time_type='ERT',
                                                start_time=start_time,
                                                end_time=end_time,
                                                evr_name=get_dict_value_default_none(entry, 'evr_name'),
                                                event_id=get_dict_value_default_none(entry, 'evr_id'),
                                                evr_level=get_dict_value_default_none(entry, 'evr_level'),
                                                message_filter=get_dict_value_default_none(entry, 'message_filter'),
                                                timeout=timeout_input)
                else:
                    # try chill query periodically since GLAD may not hold data long enough
                    evrs = ing_lib.ChillEVRQuery(data_path=step_input["data_path"],
                                                time_type='ERT',
                                                start_time=start_time,
                                                end_time=end_time,
                                                evr_name=get_dict_value_default_none(entry, 'evr_name'),
                                                evr_id=get_dict_value_default_none(entry, 'evr_id'),
                                                evr_type=get_dict_value_default_none(entry, 'evr_type'),
                                                evr_level=get_dict_value_default_none(entry, 'evr_level'),
                                                evr_module=None,
                                                message_filter=get_dict_value_default_none(entry, 'message_filter'),
                                                timeout=timeout_input)
                
                raw_count = len(evrs)

                # Apply evr_type filter
                if evr_type == "SSE":
                    evrs = [evr for evr in evrs if evr.get("fromSSE") is True]                                  
                elif evr_type == "FSW_RECORDED":
                    evrs = [evr for evr in evrs if evr.get("fromSSE") is False and evr.get("isRecorded") is True]   
                elif evr_type == "FSW_REALTIME":
                    evrs = [evr for evr in evrs if evr.get("fromSSE") is False and evr.get("isRecorded") is False]

                total_count = len(evrs)
                # evrs are sorted by time (latest last)   
                msg = f'EVRS found. raw_count: {raw_count} total_count: {total_count} Latest 5 EVRs: {evrs[-5:]}'

                logger.info(msg, extra = {
                    "event": ing_lib.EventName.QUERY_EVRS.value
                })

            except StepExecutionError as ex:
                msg = "WaitEVR query to venue failed"
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
                msg = "WaitEVR query to venue failed"
                # log statement

                error_obj = {
                        "message": msg,
                        "error_type": ing_lib.ErrorType.QUERY_ERROR.value,
                        "error_source": ing_lib.ErrorSource.VENUE_SERVICE.value,
                        "http_code_at_source": 400,
                        "details": [traceback.format_exc()]
                }

                logger.error(msg, extra = {
                    "event": ing_lib.EventName.QUERY_EVRS.value,
                    "data": error_obj
                })

                # simply raise to preserve the original exception
                return return_step_with_error(step, error_obj)

            if type(evrs) == list and len(evrs) > 0:

                evr_received_msg = 'EVR telemetry retrieved'

                logger.info(evr_received_msg, extra = {
                    "event": ing_lib.EventName.EVR_QUERY_RESPONSE.value
                })

            else:

                evr_not_received_msg = 'EVR telemetry was not found'

                logger.info(evr_not_received_msg, extra = {
                    "event": ing_lib.EventName.EVR_QUERY_RESPONSE.value
                })

            # Note: this will verify the entry
            evr_response_object.update_evr_entry(index, evrs, total_count)
            verification_status = entry["verification_status"]
            
            # push notice: verification result
            verified_msg = 'EVR telemetry verified. EVR name: {} - verification status: {}'.format(entry["evr_name"], verification_status)

            logger.info(verified_msg, extra = {
                "event": ing_lib.EventName.VERIFY_EVRS.value
            })

            intermediate_results = {
                'meta_data': {
                    'status': 'RUNNING',
                    'status_message': verified_msg
                },
                'results': evr_response_object.return_intermediate_response()
            }
            report_step_results(step, intermediate_results, None)
            
            # verification is completed when verification_status is FAIL for DOES_NOT_EXIST or
            #                           verification_status is PASS for other verification condition
            # additionally, break while loop to avoid additional 1 sec sleep.
            if (verification_condition == 'DOES_NOT_EXIST' and verification_status == "FAIL") or \
                (verification_condition != 'DOES_NOT_EXIST' and verification_status == "PASS"):
                entry_verified = True

            # Update remaining time regardless of verification_status
            # sleep only when timeout has not happened
            if timeout_copy > 0 and not entry_verified:
                time.sleep(1)
                
            timer_end = time.time()
            time_delta = timer_end - timer_start

            if timeout_copy < 5:
                display_timeout = int(timeout_copy - time_delta)
            else:
                display_timeout = 5 * math.ceil(float(timeout_copy - time_delta)/5)

                if display_timeout > timeout_input:
                    display_timeout = timeout_input

            timeout_copy = timeout_copy - time_delta

            # Check if the current time is passed the query window.
            # Use a 10 seconds margin to account for any lag in AMPCS.
            try:
                current_utc = datetime.utcnow()
                if convert_time(end_time) < (current_utc - timedelta(seconds=10.0)):
                    passed_query_window = True
                    logger.info('end_time: {} current_utc: {} passed_query_window: {}'.format(end_time, current_utc, passed_query_window))
            except:
                msg = "Failed to check the passage of the query window: {}".format(traceback.format_exc())
                logger.warning(msg)
        
        # Note that entry['verification_status'] will be the last value as verified (PASS or FAIL)
        # regardless timeout happened or not.

    step_results = evr_response_object.return_intermediate_response()
    step["execution"]["results"] = step_results
    
    for result in step_results["entries"]:
        if result["verification_status"] == "PASS":
            step["execution"]["meta_data"]["status"] = "PASS"
        else:
            step["execution"]["meta_data"]["status"] = "FAIL"
            break
    step["execution"]["meta_data"]["status_message"] = ""

    return step


def run_dummy(step):

    print('wait_evr_step.run_dummy()')
    queries = copy.deepcopy(step['execution_user_input'])

    outputs = []

    for query in queries["entries"]:

        output_dict = query

        evr_list = []
        evr_data = {
              "evr_name": "core_speed",
              "session_id": 50,
              "vcid": 12,
              "event_id": 100,
              "evr_level": "ACTIVITY_LO",
              "from_sse": True,
              "evr_message": "cool evr bro",
              "evr_module": "SSE-1234",
              "sclk": "527925356",
              "ert": "2017-032T00:23:03",
              "scet": "2017-032T00:23:01",
              "is_recorded": True
        }

        evr_list.append(evr_data)
        output_dict["total_count"] = 1
        output_dict["evr_data"] = evr_list
        outputs.append(output_dict)

    results = {
        'venue_id': ic.venue_id,
        'venue_name': ic.venue_name,
        'venue_ampcs_address': ic.venue_service_address,
        'entries': outputs
    }
    step['execution']['results'] = results
    step['execution']['meta_data']['status'] = 'PASS'
    return step
