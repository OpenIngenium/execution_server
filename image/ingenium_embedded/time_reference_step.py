from . import ingenium_config as ic
from . import ingenium_library as ing_lib
from .ingenium_library import ing_execution, get_now_utc, create_step_error, return_step_with_error
from .logging_util import logger
import copy

@ing_execution
def run(step):
    # initialize results
    results = copy.deepcopy(step['execution_user_input'])
    step['execution']['results'] = results
    
    name = results['name']

    if name in ic.standard_time_references:
        msg = 'Cannot use a reserved name of time reference. name: %s' % name
        # log statement
        error_obj = create_step_error(message=msg,
                        details=[],
                        error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                        error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                        http_code_at_source=0)

        logger.error(msg, extra = {
            "event": ing_lib.EventName.TIME_VALIDATION.value,
            "data": error_obj
        })

        return return_step_with_error(step, error_obj)
        
    time_value = get_now_utc()

    results['time_value'] = time_value
    ic.time_references[name] = time_value

    step['execution']['meta_data']['status'] = 'PASS'

    # the final results will be received by "ing_execution" decorator and be reported back to Core
    step['execution']['meta_data']['status_message'] = ''

    return step
