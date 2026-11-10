from . import ingenium_library as ing_lib
from . import ingenium_config as ic
from .ingenium_library import ing_execution, create_step_error, return_step_with_error, StepExecutionError, report_step_results
from .logging_util import logger
import copy
import traceback

@ing_execution
def run(step):
    """
    This function implements the UpdateConfig step.

    All Ingenium Step Functions only accept the step JSON as both an input and as an output.

    """
    if ic.manual_input_variables.get("step_function_name") and ic.manual_input_variables.get("step_function_name").get('actual_value') == "run_dummy":
        return run_dummy(step)

    # Pull out the GetConfig definition of the step
    entries = step['execution_user_input']['entries']

    # Walk through the elements to update and update the venue for them
    output_entries = []

    for entry in entries:

        try:
            response = ing_lib.update_venue_config(entry)
        except StepExecutionError as ex:
            msg = "UpdateVenueConfig query to venue configuration failed"
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
            msg = "UpdateVenueConfig query to venue configuration failed"
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


        # change dict entry "elem_name" to "config_elem_name"
        response["config_elem_name"] = response.pop("elem_name")

        output_entries.append(response)

    # Update the status of the step to PASS
    for output in output_entries:
        if output != None:
            step["execution"]["meta_data"]["status"] = "PASS"
        else:
            step["execution"]["meta_data"]["status"] = "FAIL"
            break

    # Update the results of the step

    results_object = {
        "venue_id": ic.venue_id,
        "venue_name": ic.venue_name,
        "entries": output_entries
    }

    step["execution"]["results"] = results_object

    step["execution"]["meta_data"]["status_message"] = "" 

    return step

def run_dummy(step):

    results = copy.deepcopy(step['execution_user_input'])

    results.update({'venue_id': ic.venue_id, 'venue_name': ic.venue_name})

    step['execution']['results'] = results
    step['execution']['meta_data']['status'] = 'PASS'
    return step
