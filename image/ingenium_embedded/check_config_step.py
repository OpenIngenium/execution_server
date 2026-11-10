from . import ingenium_library as ing_lib
from . import ingenium_config as ic
from .ingenium_library import ing_execution, create_step_error, return_step_with_error, StepExecutionError
from .logging_util import logger
import copy
import json
import traceback

@ing_execution
def run(step):
    """
    This function implements the CheckConfig step.

    All Ingenium Step Functions only accept the step JSON as both an input and as an output.

    """
    if ic.manual_input_variables.get("step_function_name") and ic.manual_input_variables.get("step_function_name").get('actual_value') == "run_dummy":
        return run_dummy(step)

    # Pull out the CheckConfig definition of the step
    elements_to_check = step['execution_user_input']['entries']

    # Check input and raise exception if bad
    for element in elements_to_check:

        if element["verification_condition"] not in ['EQUAL','NOT_EQUAL']:
            msg = "Invalid evaluation to check '{}' for element: '{}'".format(element["verification_condition"], element["config_elem_name"])
            error_obj = create_step_error(message=msg,
                            details=[],
                            error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                            error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)

            # log statement
            logger.error(msg, extra= {
                "event": ing_lib.EventName.USER_INPUT_VALIDATION.value,
                "data": error_obj
            })

            return return_step_with_error(step, error_obj)

        elif element["field_name"] not in ['TYPE','STATUS','SERIAL']:
            msg = "Invalid field to check '{}' for element: '{}'".format(element["field_name"], element["config_elem_name"])
            error_obj = create_step_error(message=msg,
                            details=[],
                            error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                            error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)

            # log statement
            logger.error(msg, extra = {
                "event": ing_lib.EventName.USER_INPUT_VALIDATION.value,
                "data": error_obj
            })

            return return_step_with_error(step, error_obj)

        elif element["field_name"] == "TYPE" and element["verification_value"] not in ["SIMULATOR","BREADBOARD","EM","FLIGHT","OTHER"]:
            msg = "Invalid type to check '{}' for element: '{}'".format(element["verification_value"], element["config_elem_name"])
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

        elif element["field_name"] == "STATUS" and element["verification_value"] not in ["INSTALLED","NOT_INSTALLED"]:
            msg = "Invalid status to check '{}' for element: '{}'".format(element["verification_value"], element["config_elem_name"])
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

    # Call the Ingenium library function to query the configuration (entire venue)
    try:
        venue_config = ing_lib.get_venue_config()

    except StepExecutionError as ex:
        msg = "GetVenueConfig query to venue failed - {}.".format(json.dumps(ex.error_obj))
        # log statement
        logger.error(msg, extra = {
            "event": ing_lib.EventName.QUERY_VENUE_CONFIGURATION.value,
            "data": {
                "message": msg,
                "error_type": ing_lib.ErrorType.QUERY_ERROR.value,
                "error_source": ing_lib.ErrorSource.VENUE_CONFIGURATION.value,
                "http_code_at_source": 400,
                "details": [str(ex.error_obj)]
            }
        })
        return return_step_with_error(step, ex.error_obj)

    except Exception as ex:
        msg = "GetVenueConfig query to venue failed - {}.".format(traceback.format_exc())
        # log statement
        error_obj = create_step_error(message=msg,
                        details=[traceback.format_exc()],
                        error_type=ing_lib.ErrorType.QUERY_ERROR.value,
                        error_source=ing_lib.ErrorSource.VENUE_CONFIGURATION.value,
                        http_code_at_source=400)

        logger.error(msg, extra = {
            "event": ing_lib.EventName.QUERY_VENUE_CONFIGURATION.value,
            "data": error_obj
        })

        return return_step_with_error(step, error_obj)

    # Iterate through the elements to check and evaluate them against the venue config and documenting that in results
    results=[]
    list_of_evaluations=[]

    for check in elements_to_check:
        # It is possible that the element is not in the venue configuration - we need to handle if it is not
        found_element=False

        # Iterate through the venue config
        for element in venue_config:

            # If the element name matches - compare the two
            if check["config_elem_name"] == element["config_elem_name"]:        # HK: need to fix this
                # Update variable to indicate the element was found
                found_element=True
                # Extract the field's value for the field to be checked
                value = element.get(check.get("field_name", "").lower())

                # Evaluate it against the predict
                if check["verification_condition"] == "EQUAL":
                    if value == check["verification_value"]:
                        evaluation = "PASS"
                    else:
                        evaluation = "FAIL"
                elif check["verification_condition"] == "NOT_EQUAL":
                    if value != check["verification_value"]:
                        evaluation = "PASS"
                    else:
                        evaluation = "FAIL"

                list_of_evaluations.append(evaluation)

                # Populate the results
                result = {"config_elem_name" : check["config_elem_name"],
                          "field_name" : check["field_name"],
                          "verification_condition" : check["verification_condition"],
                          "verification_value" : check["verification_value"],
                          "actual_value" : value,
                          "verification_status" : evaluation}

                results.append(result)

                # Exit the inner loop to procedure with the other element to check
                break



            # If the element can't be found, populate the results with input and fail the check
        if found_element == False:
            msg = "CheckConfig attempted to check Element: '{}' which is not present on venue: '{}'".format(check["config_elem_name"],ic.venue_name)
            # log statement
            logger.info(msg, extra = {
                "event": ing_lib.EventName.CONFIGURATION_ELEMENT_NOT_FOUND.value
            })
            # Populate the results
            result = {"config_elem_name": check["config_elem_name"],
                      "field_name": check["field_name"],
                      "verification_condition": check["verification_condition"],
                      "verification_value": check["verification_value"],
                      "actual_value": "NOT PRESENT ON VENUE",
                      "verification_status": "FAIL"}
            results.append(result)
            list_of_evaluations.append("FAIL")

    # Update the step status by OR'ing the individual check status
    if "FAIL" in list_of_evaluations:
        step["execution"]["meta_data"]["status"] = "FAIL"
    else:
        step["execution"]["meta_data"]["status"] = "PASS"

    # Update the results of the step

    results_object = {
        "venue_id": ic.venue_id,
        "venue_name": ic.venue_name,
        "entries": results
    }

    step["execution"]["results"] = results_object
    step["execution"]["meta_data"]["status_message"] = ""

    return step


def run_dummy(step):

    entries = step['execution_user_input']['entries']

    out_values = []
    for item in entries:
        value_dict = copy.deepcopy(item)
        value_dict['actual_value'] = value_dict['verification_value']
        value_dict['verification_status'] = 'PASS'

        out_values.append(value_dict)

    results = {
        'venue_id': ic.venue_id,
        'venue_name': ic.venue_name,
        'entries': out_values
    }
    step['execution']['results'] = results
    step['execution']['meta_data']['status'] = 'PASS'
    return step
