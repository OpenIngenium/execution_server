from . import ingenium_library as ing_lib
from . import ingenium_config as ic
from .ingenium_library import ing_execution,get_dict_value, create_step_error, return_step_with_error, StepExecutionError, \
    report_step_results, refresh_venue_tokens, validate_times, EventName, convert_time
import traceback
import time
from datetime import datetime
import copy
import json
import math
from .logging_util import logger
from .ingenium_library import ErrorType, ErrorSource, Bus1553Response, record_bus_1553_data
from .verification_lib import Verify, timedelta


def convert_value(data_type, value):

    logger.info("Data type: {}, bus response value: {}".format(data_type, value), extra = {
        "event": EventName.QUERY_1553.value
    })


    actual_value = None
    value_type = None

    # python treates signed and unsigned integers the same when type casting
    if data_type in ["INT", "UINT"]:
        try:
            actual_value = int(value)
            value_type = "INTEGER"
        except:
            msg = "Cannot convert value: {} into an integer".format(value)

            error_obj = create_step_error(message="Cannot convert value: {}, which is type: {}, into type: {}".format(value, type(value), data_type),
                        details=[],
                        error_type=ErrorType.VALUE_CONVERSION_ERROR.value,
                        error_source=ErrorSource.EMBEDDED_CODE.value,
                        http_code_at_source=0)

            logger.error(msg, extra = {
                "event": EventName.CONVERT_VALUE.value,
                "data": error_obj
            })

            raise StepExecutionError("Data type: {} not found".format(data_type), error_obj)            
            
    elif data_type == "FLOAT":
        try:
            actual_value = float(value)
            value_type = "FLOAT"
        except:
            msg = "Cannot convert value: {} into a float".format(value)
            error_obj = create_step_error(message="Cannot convert value: {}, which is type: {}, into type: {}".format(value, type(value), data_type),
                        details=[],
                        error_type=ErrorType.VALUE_CONVERSION_ERROR.value,
                        error_source=ErrorSource.EMBEDDED_CODE.value,
                        http_code_at_source=0)
            
            logger.error(msg, extra = {
                "event": EventName.TIME_CONVERSION.value,
                "data": error_obj
            })

            raise StepExecutionError("Data type: {} not found".format(data_type), error_obj)
    
    elif data_type in ["HEX", "BIN", "ENUM"]:
        actual_value = value 
        value_type = "STRING"
    else:
        msg = "Data type: {} not found".format(data_type)

        error_obj = create_step_error(message=msg,
                    details=[],
                    error_type=ErrorType.VALUE_CONVERSION_ERROR.value,
                    error_source=ErrorSource.EMBEDDED_CODE.value,
                    http_code_at_source=0)

        logger.error(msg, extra = {
            "event": EventName.TIME_CONVERSION.value,
            "data": error_obj
        })

        raise StepExecutionError(msg, error_obj)

    return actual_value, value_type
    

def calculate_next_start_time(bus_responses, entry_start_time, time_type):
    # in case nothing comes back from VS, don't alter start time
    if not bus_responses:
        return entry_start_time 
    # If SCET use latest response SCET time, else if SCLK use SCLK time
    else:
        if time_type == "SCET":
            if bus_responses[0]["time_scet"]:
                scet_split = bus_responses[0]["time_scet"].split(".")
                return scet_split[0]
            else:
                msg = "Most recent 1553 entry does not have a SCET time record."
                
                error_obj = create_step_error(message=msg,
                            details=[],
                            error_type=ErrorType.VALUE_CONVERSION_ERROR.value,
                            error_source=ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)
                
                logger.error(msg, extra = {
                    "event": EventName.TIME_CONVERSION.value,
                    "data": error_obj
                })

                raise StepExecutionError(msg, error_obj)  

        else:
            if bus_responses[0]["time_sclk"]:
                return bus_responses[0]["time_sclk"]
            else:
                msg = "Most recent 1553 entry does not have a SCLK time record."
                
                error_obj = create_step_error(message=msg,
                            details=[],
                            error_type=ErrorType.VALUE_CONVERSION_ERROR.value,
                            error_source=ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)
                
                logger.error(msg, extra = {
                    "event": EventName.TIME_CONVERSION.value,
                    "data": error_obj
                })

                raise StepExecutionError(msg, error_obj)                  


@ing_execution
def run(step):

    if ic.manual_input_variables.get("step_function_name") and ic.manual_input_variables.get("step_function_name").get('actual_value') == "run_dummy":
        return run_dummy(step)    

    step_input = copy.deepcopy(step["execution_user_input"])
    verify_wait = step_input.get("verify_wait")
    time_type = step_input.get("time_type")
    timeout_input = get_dict_value(step_input, "timeout", ic.bus_1553_timeout)
    remaining_secs = timeout_input

    # Store channel values that will be used to record channel values at the end of step
    entry_record_map = {}

    if time_type is None:
        msg = "Time type field is required"

        error_obj = create_step_error(message=msg,
                        details=[],
                        error_type=ing_lib.ErrorType.TIME_VALIDATION_ERROR.value,
                        error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                        http_code_at_source=0)

        logger.error(msg, extra = {
            "event": EventName.TIME_VALIDATION.value,
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

    bus_1553_response_object = Bus1553Response(step_input["entries"], translated_start_time, translated_end_time, start_time, end_time)
    # Initialize results so that input values are available when the step errors or is canceled.
    step['execution']['results'] = bus_1553_response_object.return_intermediate_response()

    timer_start = time.time()

    for index, entry in enumerate(step['execution']['results']["entries"]):
        # extract RAW or CONVERT value to be used later
        raw_or_convert = entry.get("raw_convert")
        verification_condition = entry.get("verification_condition")
        bus_variable = entry.get('bus_1553_var')
        verification_status = 'PENDING'
        ran_once = False
        passed_query_window = False

        if verify_wait == "VERIFY":

            while (not ran_once) or ((remaining_secs > 0) and (not passed_query_window) and (verification_status == 'PENDING')):

                refresh_venue_tokens()
                ran_once = True

                # log and update step status
                if remaining_secs <= 0:
                    status_msg = 'Searching for bus variable: {} once'.format(bus_variable)
                else:
                    status_msg = 'Searching for bus variable: {} - timeout remaining {} seconds'.format(bus_variable, max(0, remaining_secs))
                logger.info(status_msg, extra = {
                    "event": ing_lib.EventName.QUERY_1553.value
                })

                intermediate_results = {
                    'meta_data': {
                        'status': 'RUNNING', 
                        'status_message': status_msg
                    }
                }
                report_step_results(step, intermediate_results, None) 

                try:
                    bus_response = ing_lib.query_bus_1553(start_time=start_time, end_time=end_time, variables=entry.get("bus_1553_var"), timeout=timeout_input, time_type=time_type)
                except StepExecutionError as ex:
                    msg = "Bus1553 query to venue failed - {}.".format(json.dumps(ex.error_obj))

                    error_obj = create_step_error(message=msg,
                                    details=[str(ex)],
                                    error_type=ing_lib.ErrorType.QUERY_ERROR.value,
                                    error_source=ing_lib.ErrorSource.VENUE_SERVICE.value,
                                    http_code_at_source=0)

                    logger.error(msg, extra = {
                        "event": EventName.QUERY_1553.value,
                        "data": error_obj
                    })

                    return return_step_with_error(step, ex.error_obj)
                except Exception as ex:
                    msg = "Bus1553 query to venue failed - {}.".format(traceback.format_exc())
                    error_obj = create_step_error(message=msg,
                                    details=[str(ex)],
                                    error_type=ing_lib.ErrorType.QUERY_ERROR.value,
                                    error_source=ing_lib.ErrorSource.VENUE_SERVICE.value,
                                    http_code_at_source=0)
                    return return_step_with_error(step, error_obj)


                if type(bus_response) == list and len(bus_response) > 0:
                    
                    logger.info("1553 bus log venue server data object returned", extra = {
                            "event": EventName.QUERY_1553.value,
                            "data": bus_response
                        })
                    # get latest entry 
                    latest_response = bus_response[0]

                    logger.info("Latest 1553 bus log entry", extra = {
                        "event": EventName.QUERY_1553.value,
                        "data": latest_response
                    })

                    if raw_or_convert == "RAW":
                        value = latest_response.get("data_value")
                    else:
                        # if there is a converted value, use it. Else, use data_value (raw value)
                        if latest_response.get("converted_value") == "":
                            value = latest_response.get("data_value")
                        else:
                            value = latest_response.get("converted_value")

                    # get actual value by converting the value according to type
                    try:
                        actual_value, value_type = convert_value(latest_response.get('data_type'), value)
                    except StepExecutionError as ex:
                        msg = str(ex)
                        error_obj = create_step_error(message=msg,
                                    details=[],
                                    error_type=ErrorType.VALUE_CONVERSION_ERROR.value,
                                    error_source=ErrorSource.EMBEDDED_CODE.value,
                                    http_code_at_source=0)
                        return return_step_with_error(step, error_obj)    
                    
                    entry.update({"actual_value": actual_value})

                    logger.info("Converted value completed: {}".format(actual_value), extra = {
                        "event": EventName.QUERY_1553.value
                    })

                    # verify condition
                    try:
                        ver = Verify.factory(step, entry, value_type=value_type)
                        returned_query, actual_value, verification_status = ver.verify()

                        # update 1553 variable with latest results
                        bus_1553_response_object.update_bus_entry(index,latest_response, bus_variable, verification_status, actual_value)
                        status_message = '1553 bus logs verified. variable name: {} - verification status: {}'.format(entry.get("bus_1553_var"), verification_status)
                        logger.info(status_message, extra = {
                            "event": ing_lib.EventName.VERIFY_BUS_1553.value
                        })

                        intermediate_results_msg = {
                            'meta_data': {
                                'status': 'RUNNING', 
                                'status_message': status_message
                            },
                            'results': bus_1553_response_object.return_intermediate_response()
                        }

                        report_step_results(step, intermediate_results_msg, None)   

                    except StepExecutionError as ex:
                        msg = str(ex)
                        error_obj = create_step_error(message=msg,
                                    details=[],
                                    error_type=ErrorType.VALUE_CONVERSION_ERROR.value,
                                    error_source=ErrorSource.EMBEDDED_CODE.value,
                                    http_code_at_source=0)
                        return return_step_with_error(step, error_obj)   

                    bus_1553_update = {
                        "rti": latest_response.get("rti"),
                        "bus_name": latest_response.get("bus_name"),
                        "data_type": latest_response.get("data_type"),
                        "data_value": latest_response.get("data_value"),
                        "converted_value": latest_response.get("converted_value"),
                        "actual_value": str(actual_value),
                        "dictionary": latest_response.get("dictionary"),
                        "log_file": latest_response.get("log_file"),
                        "sclk": latest_response.get("time_sclk"),
                        "scet": latest_response.get("time_scet"),
                        "verification_status": verification_status 
                    }

                    logger.info("Resulting bus 1553 embedded code object", extra = {
                        "event": EventName.QUERY_1553.value,
                        "data": bus_1553_update
                    })

                    entry.update(bus_1553_update)           
                    entry_copy = copy.deepcopy(entry)
                    entry_copy.update(returned_query)
                    entry_record_map[bus_variable] = entry_copy            


                # sleep only when timeout has not happened
                if remaining_secs > 0 and verification_status != "PASS":
                    time.sleep(1)

                # always update the remaining time
                remaining_secs = timeout_input - (time.time() - timer_start)

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
                
                # If verification_status is PENDING, that means no bus messages was found.
                if verification_status == 'PENDING':
                    # If timeout is reached, set verification_status.
                    if remaining_secs <= 0 or passed_query_window:
                        if verification_condition == 'NOT_PRESENT':
                            status_message = 'Bus 1553 variable not found until timeout. Bus 1553 variable: {} Passes NOT_PRESENT condition'.format(entry.get("bus_1553_var"))
                            verification_status = 'PASS'
                        else:
                            status_message = 'Bus 1553 variable not found until timeout. Fails {} condition'.format(verification_condition)
                            verification_status = 'FAIL'
                    else:
                        status_message = 'Bus 1553 variable not found. Continue to check. Remaining seconds: {:.2f}'.format(remaining_secs)

                    bus_1553_response_object.update_entry_verification_status(index, verification_status)

                    # log it.  Note that log already happened when verification_status is not PENDING.
                    logger.info(status_message, extra = {
                        'event': ing_lib.EventName.QUERY_1553.value
                    })

                # update bus message response
                intermediate_results = {
                    'meta_data': {
                        'status': 'RUNNING', 
                        'status_message': status_message
                    },
                    'results': bus_1553_response_object.return_intermediate_response()
                }
                report_step_results(step, intermediate_results, None)
        # else if "WAIT"
        else:
            entry_start_time = start_time
            entry_verified = False
            display_timeout = timeout_input

            while (not ran_once) or (remaining_secs > 0 and (not entry_verified)):

                refresh_venue_tokens()
                ran_once = True
                timer_start = time.time()

                if remaining_secs <= 0:
                    search_msg = 'Searching for bus variable: {} once'.format(bus_variable)
                else:
                    search_msg = 'Searching for bus variable: {} - timeout remaining {} seconds'.format(bus_variable, display_timeout)
                logger.info(search_msg, extra = {
                    "event": ing_lib.EventName.QUERY_1553.value
                })

                search_eha_msg = {
                    'meta_data': {
                        'status': 'RUNNING', 
                        'status_message': search_msg
                    }
                }
                report_step_results(step, search_eha_msg, None)

                try:
                    bus_response = ing_lib.query_bus_1553(start_time=entry_start_time, end_time=end_time, variables=entry.get("bus_1553_var"), timeout=timeout_input, time_type=time_type)
                except StepExecutionError as ex:
                    msg = "Bus1553 query to venue failed - {}.".format(json.dumps(ex.error_obj))

                    error_obj = create_step_error(message=msg,
                                    details=[str(ex)],
                                    error_type=ing_lib.ErrorType.QUERY_ERROR.value,
                                    error_source=ing_lib.ErrorSource.VENUE_SERVICE.value,
                                    http_code_at_source=400)

                    logger.error(msg, extra = {
                        "event": EventName.QUERY_1553.value,
                        "data": error_obj
                    })

                    return return_step_with_error(step, ex.error_obj)
                except Exception as ex:
                    msg = "Bus1553 query to venue failed - {}.".format(traceback.format_exc())
                    error_obj = create_step_error(message=msg,
                                    details=[str(ex)],
                                    error_type=ing_lib.ErrorType.QUERY_ERROR.value,
                                    error_source=ing_lib.ErrorSource.VENUE_SERVICE.value,
                                    http_code_at_source=400)
                    return return_step_with_error(step, error_obj)
                
                if bus_response:

                    logger.info("1553 bus log venue server data object returned", extra = {
                        "event": EventName.QUERY_1553.value,
                        "data": bus_response
                    })
                    for res in bus_response:
                        
                        logger.info("Individual bus log entry", extra = {
                            "event": EventName.QUERY_1553.value,
                            "data": res
                        })

                        if raw_or_convert == "RAW":
                            value = res.get("data_value")
                        else:
                            # if there is a converted value, use it. Else, use data_value (raw value)
                            if res.get("converted_value") == "":
                                value = res.get("data_value")
                            else:
                                value = res.get("converted_value")
                        
                        # get actual value by converting the value according to type
                        try:
                            actual_value, value_type = convert_value(res.get('data_type'), value)
                        except StepExecutionError as ex:
                            msg = str(ex)
                            error_obj = create_step_error(message=msg,
                                        details=[],
                                        error_type=ErrorType.VALUE_CONVERSION_ERROR.value,
                                        error_source=ErrorSource.EMBEDDED_CODE.value,
                                        http_code_at_source=0)
                            return return_step_with_error(step, error_obj)                        
                        
                        logger.info("Converted value completed: {}".format(actual_value), extra = {
                            "event": EventName.QUERY_1553.value
                        })

                        # update entry with actual value
                        entry.update({"actual_value": actual_value})

                        try:
                            ver = Verify.factory(step, entry, value_type=value_type)
                            returned_query, actual_value, verification_status = ver.verify()
                        except StepExecutionError as ex:
                            msg = str(ex)
                            error_obj = create_step_error(message=msg,
                                        details=[],
                                        error_type=ErrorType.VALUE_CONVERSION_ERROR.value,
                                        error_source=ErrorSource.EMBEDDED_CODE.value,
                                        http_code_at_source=0)
                            return return_step_with_error(step, error_obj)                             


                        if verification_status == "PASS":
                            bus_1553_update = {
                                "rti": res.get("rti"),
                                "bus_name": res.get("bus_name"),
                                "data_type": res.get("data_type"),
                                "data_value": res.get("data_value"),
                                "converted_value": res.get("converted_value"),
                                "actual_value": str(actual_value),
                                "dictionary": res.get("dictionary"),
                                "log_file": res.get("log_file"),
                                "sclk": res.get("time_sclk"),
                                "scet": res.get("time_scet"),
                                "verification_status": verification_status 
                            }
                            entry.update(bus_1553_update) 
                            entry_copy = copy.deepcopy(entry)
                            entry_copy.update(returned_query)
                            entry_record_map[bus_variable] = entry_copy  
                            break

                else:
                    verification_status = "PASS" if verification_condition == "NOT_PRESENT" else "FAIL"
                    actual_value = ""
                
                logger.info("This bus entry will be written into bus response object", extra = {
                    "event": EventName.QUERY_1553.value,
                    "data": entry
                })

                logger.info("Entry verification status: {}".format(verification_status), extra = {
                    "event": EventName.QUERY_1553.value
                })

                # update bus response with latest telemetry results
                bus_1553_response_object.update_bus_entry(index, entry, bus_variable, verification_status, actual_value)
                
                bus_intermediate_response = '1553 bus logs verified. variable name: {} - verification status: {}'.format(entry.get("bus_1553_var"), verification_status)
                logger.info(bus_intermediate_response, extra = {
                    "event": ing_lib.EventName.VERIFY_BUS_1553.value
                })

                intermediate_results_msg = {
                    'meta_data': {
                        'status': 'RUNNING', 
                        'status_message': bus_intermediate_response
                    },
                    'results': bus_1553_response_object.return_intermediate_response()
                }
                report_step_results(step, intermediate_results_msg, None)  

                if (verification_condition == 'NOT_PRESENT' and verification_status == "FAIL") or \
                   (verification_condition != 'NOT_PRESENT' and verification_status == "PASS"):
                    entry_verified = True

                # Update query time range
                try:
                    entry_start_time = calculate_next_start_time(bus_response, entry_start_time, time_type)
                except StepExecutionError as ex:
                    msg = str(ex)
                    error_obj = create_step_error(message=msg,
                                details=[],
                                error_type=ErrorType.VALUE_CONVERSION_ERROR.value,
                                error_source=ErrorSource.EMBEDDED_CODE.value,
                                http_code_at_source=0)
                    return return_step_with_error(step, error_obj)

                # Update remaining time regardless of verification_status
                # sleep only when timeout has not happened
                if remaining_secs > 0 and not entry_verified:
                    time.sleep(1)
                    
                # always update the remaining time
                timer_end = time.time()
                time_delta = timer_end - timer_start

                if remaining_secs < 5:
                    display_timeout = int(remaining_secs - time_delta)
                else:
                    display_timeout = 5 * math.ceil(float(remaining_secs - time_delta)/5)

                    if display_timeout > timeout_input:
                        display_timeout = timeout_input
                
                remaining_secs = remaining_secs - time_delta


            if verification_status != "PASS":
                verification_status = "FAIL"
                bus_1553_response_object.update_entry_verification_status(index, verification_status)
    
    logger.info("Final bus 1553 response object", extra = {
        "event": EventName.QUERY_1553.value,
        "data": bus_1553_response_object.return_intermediate_response()
    })

    for bus_var in entry_record_map:
        record_bus_1553_data(entry_record_map[bus_var])

    step_results = bus_1553_response_object.return_intermediate_response()
    step["execution"]["results"] = step_results
    
    # determine if step passed or failed
    for entry in step_results["entries"]:
        if entry["verification_status"] == "PASS":
            step["execution"]["meta_data"]["status"] = "PASS"
        elif entry["verification_status"] == "FAIL":
            step["execution"]["meta_data"]["status"] = "FAIL"
            break
    
    step["execution"]["meta_data"]["status_message"] = ""

    return step

def run_dummy(step):
    inputs = step['execution_user_input']


    # Pull out the GDSStep definition of the step
    entries = step['execution_user_input']['entries']

    results_entries = copy.deepcopy(entries)

    for entry in results_entries:
        entry['rti'] = 0 
        entry['bus_name'] = '' 
        entry['error_status'] = '' 
        entry['data_type'] = '' 
        entry['converted_value'] = '' 
        entry['actual_value'] = '' 
        entry['dictionary'] = '' 
        entry['log_file'] = '' 
        entry['sclk'] = '' 
        entry['scet'] = '' 
        entry['verification_status'] = 'PASS' 

    # Populate the query results
    step['execution']['results']['venue_id']=ic.venue_id
    step['execution']['results']['venue_name'] = ic.venue_name
    step['execution']['results']['venue_ampcs_address'] = ic.venue_service_address
    step["execution"]['results']['entries']= results_entries

    # Update the status of the step to PASS
    step['execution']['meta_data']['status'] = 'PASS'
    step['execution']['meta_data']['status_message'] = '' 

    return step    
