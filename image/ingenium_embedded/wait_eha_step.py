from . import ingenium_config as ic
import copy
from .ingenium_library import ing_execution
from .verification_lib import run_eha_verification

@ing_execution
def run(step):

    if ic.manual_input_variables.get("step_function_name") and ic.manual_input_variables.get("step_function_name").get('actual_value') == "run_dummy":
        return run_dummy(step)

    return run_eha_verification(step, True)

def run_dummy(step):

    print('wait_eha_step.run_dummy()')
    queries = copy.deepcopy(step['execution_user_input'])

    outputs = []

    for query in queries["entries"]:

        eha_data = {
            "channel_type": "SSE",
            "channel_id": "DMX-0404",
            "channel_name": "Temperature Telemetry",
            "data_path": "SIDE A",
            "dn_eu": "DN",
            "verify_on": "VALUE",
            "verification_condition": "RECORD",
            "verification_values": [
              10
            ],
            "dn": "123123",
            "eu": 50,
            "session_id": 36,
            "channel_status": "HEALTHY",
            "sclk": "676745241",
            "ert": "2017-283T08:51:00",
            "scet": "2017-283T08:51:00",
            "actual_value": "123",
            "verification_status": "PASS"
          }


        outputs.append(eha_data)

    results = {
        'venue_id': ic.venue_id,
        'venue_name': ic.venue_name,
        'venue_ampcs_address': ic.venue_service_address,
        'entries': outputs
    }
    step['execution']['results'] = results
    step['execution']['meta_data']['status'] = 'PASS'
    return step
