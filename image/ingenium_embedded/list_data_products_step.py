from . import ingenium_library as ing_lib
from . import ingenium_config as ic
from .ingenium_library import ing_execution, get_dict_value_default_none, get_dict_value, \
    create_step_error, return_step_with_error, StepExecutionError, report_step_results, DpResponse, EventName, validate_times
import traceback
import copy
import json
import time
from .logging_util import logger


@ing_execution
def run(step):
    """
    This function implements the ListDataProducts step

    """
    if ic.manual_input_variables.get("step_function_name") and ic.manual_input_variables.get("step_function_name").get('actual_value') == "run_dummy":
        return run_dummy(step)

    # Pull out the ListDataProducts definition of the step
    step_input = copy.deepcopy(step["execution_user_input"])

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

    data_path = step_input.get('data_path')

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

    for index, entry in enumerate(step['execution']['results']["entries"]):

        # make sure to check if "product_status_filter" exists, that it conforms to specified format 
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
        # For data products, each entry only needs to be queried ONCE. Whatever results come from the venue server call is evaluated accordingly.

        try:
            search_msg = 'Searching for data product ap_id: {}'.format(entry['apid'])
            logger.info(search_msg, extra= {
                "event": ing_lib.EventName.QUERY_DATA_PRODUCTS.value
            })
            data_products = ing_lib.DataProductsQuery(data_path=data_path,
                                                    dp_status=get_dict_value_default_none(entry, 'product_status_filter'),
                                                    ap_ids=get_dict_value_default_none(entry, 'apid'),
                                                    time_type=get_dict_value_default_none(step_input, 'time_type'),
                                                    start_time=start_time,
                                                    end_time=end_time,
                                                    timeout=get_dict_value(step_input, 'timeout', ic.dp_timeout))

        except StepExecutionError as ex:

            return return_step_with_error(step, ex.error_obj)

        except Exception as ex:

            msg = "ListDataProducts query to venue failed"

            error_obj = {
                "message": msg,
                "error_type": ing_lib.ErrorType.QUERY_ERROR.value,
                "error_source": ing_lib.ErrorSource.VENUE_SERVICE.value,
                "http_code_at_source": 400,
                "details": [traceback.format_exc()]                
            }

            logger.error(msg, extra = {
                "event": ing_lib.EventName.QUERY_DATA_PRODUCTS.value,
                "data": error_obj
            })

            return return_step_with_error(step, error_obj)

        if isinstance(data_products, list):
            entry["total_count"] = len(data_products)
        else:
            msg = "Expected a list of data products but got: {}".format(data_products)
            
            error_obj = {
                "message": msg,
                "error_type": ing_lib.ErrorType.QUERY_ERROR.value,
                "error_source": ing_lib.ErrorSource.VENUE_SERVICE.value,
                "http_code_at_source": 400,
                "details": [data_products]                
            }

            logger.error(msg, extra = {
                "event": ing_lib.EventName.QUERY_DATA_PRODUCTS.value,
                "data": error_obj
            })

            return return_step_with_error(step, error_obj)


        dp_response_object.update_dp_entry(index, data_products, entry["total_count"])

    step_results = dp_response_object.return_intermediate_response()
    step["execution"]["results"] = step_results
    
    # post processing after all entries have been evaluated
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
            "verification_status": "PASS",
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
