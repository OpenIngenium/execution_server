from . import ingenium_library as ing_lib
from . import ingenium_config as ic
from .ingenium_library import ing_execution, create_step_error, return_step_with_error, StepExecutionError, report_step_results
import traceback
from .logging_util import logger

@ing_execution
def run(step):
    """
    This function implements the GetConfig step.

    All Ingenium Step Functions only accept the step JSON as both an input and as an output.

    """

    if ic.manual_input_variables.get("step_function_name") and ic.manual_input_variables.get("step_function_name").get('actual_value') == "run_dummy":
        return run_dummy(step)

    # Pull out the GetConfig definition of the step
    elements = step['execution_user_input']['entries']
    get_all = step["execution_user_input"]["get_all"]

    # Extract the list of elements to query
    elements_to_query=[]
    for element in elements:
        elements_to_query.append(element['config_elem_name'])          # HK: need to fix this


    # Call the Ingenium library function to query the configuration (entire venue)
    # This returns a list of dictionaries (which matches the format required for the step
    try:
        venue_config = ing_lib.get_venue_config()

    except StepExecutionError as ex:
        msg = "GetVenueConfig query failed"
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
        msg = "GetVenueConfig query failed"
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

    out_entries = []
    venue_config_names = []
    venue_config_elem_state = {}

    # put venue config element names in list for easier searching
    for item in venue_config:
        venue_config_names.append(item["config_elem_name"])

    if get_all:
        for value in venue_config_names:
            create_output_entry(out_entries, venue_config, value)
    else:
        # for each "element to query" search through returned list of venue configs. If one cannot be found, then FAIL. If all can be found PASS         
        for value in elements_to_query:
            if value in venue_config_names:
                create_output_entry(out_entries, venue_config, value)
                venue_config_elem_state[value] = True
            else:
                venue_config_elem_state[value] = False

    elements_not_found = [key for key,value in venue_config_elem_state.items() if value == False]

    if len(elements_not_found) > 0:
        step["execution"]["meta_data"]["status"]="FAIL"
        step["execution"]["meta_data"]["message"] = "Venue config elements were not found: {}".format(elements_not_found)
    else:
        step["execution"]["meta_data"]["status"]="PASS"

    results_object = {
        "venue_id": ic.venue_id,
        "venue_name": ic.venue_name,
        "entries": out_entries
    }

    step["execution"]["results"] = results_object

    step["execution"]["meta_data"]["status_message"] = "" 

    return step

# if an "element to query" is found in the queried list of venue config elements, append found element and return the aggregated list. 
def create_output_entry(out_entries, venue_config, key):

    for config in venue_config:
        if key == config["config_elem_name"]:
            results={"config_elem_name":config["config_elem_name"],"type":config["type"],"status":config["status"],"serial":config["serial"]}
            out_entries.append(results)             

    return out_entries

def run_dummy(step):

    config_elem_ids = step['execution_user_input']['entries']

    out_values = []
    for idx, item in enumerate(config_elem_ids):
        config_elem_name = item['config_elem_name']

        value_dict = {
            'config_elem_name': config_elem_name,
            'type': 'EM',
            'status': 'INSTALLED',
            'serial': 'serial_number_' + str(idx),
        }
        out_values.append(value_dict)

    results = {
        'venue_id': ic.venue_id,
        'venue_name': ic.venue_name,
        'entries': out_values
    }
    step['execution']['results'] = results

    step['execution']['meta_data']['status'] = 'PASS'

    return step
