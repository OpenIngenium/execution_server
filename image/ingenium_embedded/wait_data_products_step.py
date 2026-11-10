from . import ingenium_library as ing_lib
from . import ingenium_config as ic
from .ingenium_library import EventName, ing_execution, get_dict_value_default_none, get_dict_value, create_step_error, return_step_with_error, StepExecutionError, \
    validate_times, report_step_results, DpResponse, refresh_venue_tokens
import traceback
from .logging_util import logger
import copy
import time
import json
import math


@ing_execution
def run(step):
    """
    This function implements the ListDataProducts step

    """
    if ic.manual_input_variables.get("step_function_name") and ic.manual_input_variables.get("step_function_name").get('actual_value') == "run_dummy":
        return run_dummy(step)

    # Pull out the ListDataProducts definition of the step

    step_input = copy.deepcopy(step["execution_user_input"])
    timeout_input = get_dict_value(step_input, "timeout", ic.dp_timeout)
    timeout_copy = timeout_input

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

    dp_response_object = DpResponse(step_input["entries"], translated_start_time, translated_end_time, start_time, end_time)
    # initialize results so that input values are available when the step errors or is canceled.
    step['execution']['results'] = dp_response_object.return_intermediate_response()

    if get_dict_value_default_none(step_input, "data_path") is None:

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


    entries_msg = "Input entries: {}".format(step_input["entries"])
    logger.info(entries_msg, extra = {
        "event": ing_lib.EventName.QUERY_DATA_PRODUCTS.value
    })

    for index, entry in enumerate(step['execution']['results']["entries"]):

        data = False
        display_timeout = timeout_copy
        ran_once = False 
        entry["verification_status"] = "PENDING"

        # make sure that verification value is a number 
        try:
            int(entry["verification_value"])
        except:
            msg = "Verification value: {} is not a number".format(entry["verification_value"])
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

        if entry.get("product_status_filter"):
            if entry.get("product_status_filter") not in ["ALL", "COMPLETE", "PARTIAL"]:
                
                error_obj = {
                    "message": "User input: '{}'. Acceptable inputs: ['ALL', 'COMPLETE', 'PARTIAL']".format(entry.get("product_status_filter")),
                    "error_type": ing_lib.ErrorType.USER_INPUT_ERROR.value,
                    "error_source": ing_lib.ErrorSource.EMBEDDED_CODE.value,
                    "http_code_at_source": 400,
                    "details": []                
                }

                return return_step_with_error(step, error_obj)
                
        #while timeout_copy > 0 and data is False:
        while (not ran_once) or (timeout_copy > 0 and entry["verification_status"] != "PASS"):

            refresh_venue_tokens()
            ran_once = True
            timer_start = time.time()

            if timeout_copy <=0:
                search_msg = "Search for Data product ap_id: {} once".format(entry["apid"])
            else:    
                search_msg = "Searching for Data product ap_id: {} - timeout remaining {} seconds".format(entry["apid"], display_timeout)


            logger.info(search_msg, extra = {
                "event": ing_lib.EventName.QUERY_DATA_PRODUCTS.value
            })

            # push notice: search for EHA telemetry
            search_evr_msg = {
                'meta_data': {
                    'status': 'RUNNING',
                    'status_message': search_msg
                }
            }
            report_step_results(step, search_evr_msg, None)

            total_count = 0

            try:
                data_products = ing_lib.DataProductsQuery(data_path=step_input["data_path"],
                                                          dp_status=get_dict_value_default_none(entry, 'product_status_filter'),
                                                          ap_ids=get_dict_value_default_none(entry, 'apid'),
                                                          start_time=start_time,
                                                          end_time=end_time,
                                                          timeout=get_dict_value(step_input, 'timeout', ic.dp_timeout))

                total_count = len(data_products)

                msg = "The following data products were retrieved from Venue Server: {}".format(data_products)
                logger.info(msg, extra= {
                    "event": ing_lib.EventName.QUERY_DATA_PRODUCTS.value
                })

            except StepExecutionError as ex:
                # need to log the error
                msg = "WaitDataProducts query to venue failed"
                logger.error(msg, extra = {
                    "event": ing_lib.EventName.QUERY_DATA_PRODUCTS.value,
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
                # need to log the error
                msg = "WaitDataProducts query to venue failed"
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

                return return_step_with_error(step, error_obj)

            dp_response_object.update_dp_entry(index, data_products, total_count)

            if entry["verification_status"] == "PASS":
                data = True
                break

            # Update remaining time regardless of verification_status
            if timeout_copy > 0:
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
        
        if timeout_copy <= 0 and data == False:
            entry["verification_status"] = "FAIL"

    step_results = dp_response_object.return_intermediate_response()
    step["execution"]["results"] = step_results
    
    for result in step_results["entries"]:
        if result["verification_status"] == "FAIL":
            step["execution"]["meta_data"]["status"] = "FAIL"
            break
        else:
            step["execution"]["meta_data"]["status"] = "PASS"

    step["execution"]["meta_data"]["status_message"] = "" 

    return step

def run_dummy(step):

    queries = copy.deepcopy(step['execution_user_input'])

    outputs = []

    for query in queries["entries"]:

        dataproduct_list = {
            "apid": 247,
            "product_status_filter": "good stuff",
            "verification_condition": "EQUAL",
            "verification_value": 1,
            "verification_ok": True,
            "total_count": 1,
            "products": [
                {
                    "session_id": 10,
                    "vcid": 0,
                    "dp_status": "COMPLETE",
                    "apid": 247,
                    "apid_product_type": "flight",
                    "file_path": "/home/directory/d.xml",
                    "file_size": 50,
                    "creation_time": "2017-283T08:50:47",
                    "sclk": "0561209980",
                    "ert": "2017-283T08:51:00",
                    "scet": "2017-283T08:50:47"
                }
            ]
        }

        outputs.append(dataproduct_list)

    results = {
        'venue_id': ic.venue_id,
        'venue_name': ic.venue_name,
        'venue_ampcs_address': ic.venue_service_address,
        "entries": outputs
    }

    step['execution']['results'] = results
    step['execution']['meta_data']['status'] = 'PASS'
    return step
