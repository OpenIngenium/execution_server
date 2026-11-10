from . import ingenium_config as ic
from . import ingenium_library as ing_lib
from .ingenium_library import ing_execution, create_step_error, return_step_with_error, StepExecutionError, get_dict_value_default_none, \
    get_dict_value, ErrorType, ErrorSource
from .logging_util import logger
import copy
import sys

def convert_units(measured_units, units, min_value, max_value, actual_value):

    '''
    logic: convert all units to smallest unit.

    Convert "KiloOhm" and "MegaOhm" in terms of smallest unit "Ohm"
    Convert "Volt" in terms of smallest unit "miliVolt"
    '''
    # for units convert min and max values
    if units == "KiloOhm":
        min_value *= 1000
        max_value *= 1000
    elif units == "MegaOhm":
        min_value *= 1000000
        max_value *= 1000000
    elif units == "Volt":
        min_value *= 1000
        max_value *= 1000

    if measured_units == "KiloOhm":
        actual_value *= 1000
    elif measured_units == "MegaOhm":
        actual_value *= 1000000
    elif measured_units  == "Volt":
        actual_value *= 1000


    return min_value, max_value, actual_value

@ing_execution
def run(step):

    # initialize results
    results = copy.deepcopy(step['execution_user_input'])
    for entry in results['entries']:
        entry['verification_status'] = 'PENDING'
    step['execution']['results'] = results
 
    for entry in results['entries']:
        # process actual value
        actual_value = get_dict_value_default_none(entry, 'actual_value')    
        units = get_dict_value_default_none(entry, 'unit')
        measured_units = get_dict_value(entry, 'measured_unit', units)

        # check if actual value is None, and whether there is an "OL" present
        if actual_value is None:
            msg = 'measured value was not provided'
            error_obj = create_step_error(message=msg,
                details=[],
                error_type=ErrorType.USER_INPUT_ERROR.value,
                error_source=ErrorSource.EMBEDDED_CODE.value,
                http_code_at_source=0)
            logger.error(msg, extra = {
                "event": ing_lib.EventName.VERIFY_MANUAL_EIP.value,
                "data": error_obj
            })
            return return_step_with_error(step, error_obj)
        else:
            if "ol" in actual_value.lower() and actual_value == "OL":
                if units not in ['Ohm', 'KiloOhm', 'MegaOhm']:
                    msg = "Input 'OL' can only be used with the following units ['Ohm', 'KiloOhm', 'MegaOhm']"
                    error_obj = create_step_error(message=msg,
                        details=[],
                        error_type=ErrorType.USER_INPUT_ERROR.value,
                        error_source=ErrorSource.EMBEDDED_CODE.value,
                        http_code_at_source=0)
                    logger.error(msg, extra = {
                        "event": ing_lib.EventName.USER_INPUT_VALIDATION.value,
                        "data": error_obj
                    })
                    return return_step_with_error(step, error_obj)  
                actual_value_float = sys.float_info.max
            elif "ol" in actual_value.lower() and actual_value != "OL":
                msg = "Please use capital 'OL' to specify 'over load'"
                error_obj = create_step_error(message=msg,
                    details=[],
                    error_type=ErrorType.USER_INPUT_ERROR.value,
                    error_source=ErrorSource.EMBEDDED_CODE.value,
                    http_code_at_source=0)
                logger.error(msg, extra = {
                    "event": ing_lib.EventName.USER_INPUT_VALIDATION.value,
                    "data": error_obj
                })
                return return_step_with_error(step, error_obj)  
            else:
                try:
                    actual_value_float = float(actual_value)
                except:       
                    msg = 'measured value was not a number. actual_value: {}'.format(actual_value)
                    error_obj = create_step_error(message=msg,
                        details=[],
                        error_type=ErrorType.USER_INPUT_ERROR.value,
                        error_source=ErrorSource.EMBEDDED_CODE.value,
                        http_code_at_source=0)
                    logger.error(msg, extra = {
                        "event": ing_lib.EventName.VERIFY_MANUAL_EIP.value,
                        "data": error_obj
                    })    
                    return return_step_with_error(step, error_obj)        

        # process min value
        min_value_float = None
        min_value = get_dict_value_default_none(entry, 'min_value')
        if min_value is not None:
            try:
                min_value_float = float(min_value)
            except:       
                msg = 'min value was not a number. min_value: {}'.format(min_value)
                error_obj = create_step_error(message=msg,
                    details=[],
                    error_type=ErrorType.USER_INPUT_ERROR.value,
                    error_source=ErrorSource.EMBEDDED_CODE.value,
                    http_code_at_source=0)
                logger.error(msg, extra = {
                    "event": ing_lib.EventName.VERIFY_MANUAL_EIP.value,
                    "data": error_obj
                })               
                return return_step_with_error(step, error_obj)
        else:
            # if no min value provided, default to -infinity
            min_value_float = float("-inf")             
      
        # process max value
        max_value_float = None
        max_value = get_dict_value_default_none(entry, 'max_value')

        if max_value is not None:   
            try:
                max_value_float = float(max_value)
            except:       
                msg = 'max value was not a number. max_value: {}'.format(max_value)
                error_obj = create_step_error(message=msg,
                    details=[],
                    error_type=ErrorType.USER_INPUT_ERROR.value,
                    error_source=ErrorSource.EMBEDDED_CODE.value,
                    http_code_at_source=0)
                logger.error(msg, extra = {
                    "event": ing_lib.EventName.VERIFY_MANUAL_EIP.value,
                    "data": error_obj
                }) 
                return return_step_with_error(step, error_obj)
        else:
            # if no max value provided, default to infinity
            max_value_float = float("inf")        

        # We need to check that both "unit" and "measured_unit" are of the same unit type.
        # "Ohm"'s with "Ohm"'s and "Volt"'s with "Volt"'s. Otherwise, throw error.
        if "Ohm" in units:
            if "Ohm" not in measured_units:
                err_msg = "Quantity kinds do not match. units = '{}', measured units = '{}'".format(units, measured_units)
                error_obj = create_step_error(message=err_msg,
                    details=[],
                    error_type=ErrorType.USER_INPUT_ERROR.value,
                    error_source=ErrorSource.EMBEDDED_CODE.value,
                    http_code_at_source=0)
                logger.error(err_msg, extra = {
                    "event": ing_lib.EventName.USER_INPUT_VALIDATION.value,
                    "data": error_obj
                })
                return return_step_with_error(step, error_obj)

        if "Volt" in units:
            if "Volt" not in measured_units:
                err_msg = "Quantity kinds do not match. units = '{}', measured units = '{}'".format(units, measured_units)
                error_obj = create_step_error(message=err_msg,
                    details=[],
                    error_type=ErrorType.USER_INPUT_ERROR.value,
                    error_source=ErrorSource.EMBEDDED_CODE.value,
                    http_code_at_source=0)
                logger.error(err_msg, extra = {
                    "event": ing_lib.EventName.USER_INPUT_VALIDATION.value,
                    "data": error_obj
                })
                return return_step_with_error(step, error_obj)

        # reduce max value, min value and measured value to lowest units
        min_value_converted, max_value_converted, actual_value_converted = convert_units(measured_units, units, min_value_float,
                                                                                         max_value_float, actual_value_float)
        # If no min or max is specified, consider it as PASS, main comparison logic
        if (actual_value_converted >= min_value_converted) and (actual_value_converted <= max_value_converted):
            entry['verification_status'] = 'PASS'
        else:
            entry['verification_status'] = 'FAIL'

    # update step results
    for entry in results['entries']:
        if entry["verification_status"] == "PASS":
            step["execution"]["meta_data"]["status"] = "PASS"
        else:
            step["execution"]["meta_data"]["status"] = "FAIL"
            break

    # reset status_message
    step["execution"]["meta_data"]["status_message"] = ""   
    return step
