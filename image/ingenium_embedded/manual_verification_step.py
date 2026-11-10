from . import ingenium_config as ic
from . import ingenium_library as ing_lib
from .ingenium_library import ing_execution
from .logging_util import logger
import copy

@ing_execution
def run(step):

    if ic.variables.get('step_function_name') == 'run_dummy':
        return run_dummy(step)

    results = copy.deepcopy(step['execution_user_input'])
    step["execution"]["results"] = results

    if results["verification_status"] == "PASS":
        # log statement
        msg = "Manual verification status - 'PASS'"
        logger.info(msg, extra= {
            "event": ing_lib.EventName.MANUAL_VERIFICATION.value
        })    
        step["execution"]["meta_data"]["status"] = "PASS"
    else:
        # log statement
        msg = "Manual verification status - 'FAIL'"
        logger.info(msg, extra= {
            "event": ing_lib.EventName.MANUAL_VERIFICATION.value
        })   
        step["execution"]["meta_data"]["status"] = "FAIL"


    step["execution"]["meta_data"]["status_message"] = "" 

    return step

def run_dummy(step):
    
    user_input = step["execution_user_input"]
    step['execution']['results'] = user_input
    step['execution']['meta_data']['status'] = 'PASS'
    return step
