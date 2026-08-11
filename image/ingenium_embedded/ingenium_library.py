################ Imports

import time
from datetime import datetime, timedelta
import traceback
from operator import itemgetter
import json
import copy
import requests
import os
import tarfile
import redis
from . import ingenium_config as ic
from .logging_util import logger
import jwt
import enum
from collections import OrderedDict
import boto3
from botocore.exceptions import ClientError

EXECUTION_SWITCH_WAIT_SEC = os.environ.get('EXECUTION_SWITCH_WAIT_SEC', '10')
EXECUTION_SWITCH_WAIT = 'execution-switch-wait'
EXECUTION_SWITCH_WAIT_FLAG = 'execution-switch-wait-flag'

class ErrorType(enum.Enum):
    #######
    # IMPORTANT: The enum list must match with error_type in Core API spec
    #######
    USER_INPUT_ERROR = "USER_INPUT_ERROR"
    DISPATCH_ERROR = "DISPATCH_ERROR"
    VERIFICATION_ERROR = "VERIFICATION_ERROR"
    VENUE_SERVICE_ERROR = "VENUE_SERVICE_ERROR"
    QUERY_ERROR = "QUERY_ERROR"
    TIMEOUT = "TIMEOUT"
    INGENIUM_SERVICE_ERROR = "INGENIUM_SERVICE_ERROR"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    REPORTING_ERROR = "REPORTING_ERROR"
    DATA_PATH_ERROR = "DATA_PATH_ERROR"
    ELEMENT_NOT_FOUND = "ELEMENT_NOT_FOUND"
    STEP_ERROR = "STEP_ERROR"
    CONDITION_EVALUATION_ERROR = "CONDITION_EVALUATION_ERROR"
    CANNOT_RELATE_DATA_PATH = "CANNOT_RELATE_DATA_PATH"
    VALUE_CONVERSION_ERROR = "VALUE_CONVERSION_ERROR"
    TIME_VALIDATION_ERROR = "TIME_VALIDATION_ERROR"

class ErrorSource(enum.Enum):

    EMBEDDED_CODE = "EMBEDDED_CODE"
    VENUE_CONFIGURATION = "VENUE_CONFIGURATION"
    VENUE_SERVICE = "VENUE_SERVICE"

class EventName(enum.Enum):

    USER_INPUT_VALIDATION = "USER INPUT VALIDATION"
    QUERY_VENUE_CONFIGURATION = "QUERY VENUE CONFIGURATION"
    CONFIGURATION_ELEMENT_NOT_FOUND = "CONFIGURATION ELEMENT NOT FOUND"
    DATA_PATH_CHECK = "DATA PATH CHECK"
    DISPATCH_COMMAND_BINARY_FILE = "DISPATCH COMMAND BINARY FILE"
    DISPATCH_COMMAND_SCMF = "DISPATCH COMMAND SCMF"
    DISPATCH_COMMAND_SSE = "DISPATCH COMMAND SSE"
    VERIFY_COMMAND = "VERIFY COMMAND"
    DISPATCH_COMMAND_FSW = "DISPATCH COMMAND FSW"
    DISPATCH_COMMAND_HW = "DISPATCH COMMAND HW"
    VERIFY_ENVIRONMENT_TEMP = "VERIFY ENVIRONMENT TEMP"
    VERIFY_ENVIRONMENT_HUMIDITY = "VERIFY ENVIRONMENT HUMIDITY"
    MTAK_SHUTDOWN = "MTAK SHUTDOWN"
    MTAK_START = "MTAK START"
    QUERY_EHAS = "QUERY EHAS"
    QUERY_DATA_PRODUCTS = "QUERY DATA PRODUCTS"
    VERIFY_MANUAL_INPUTS = "VERIFY MANUAL INPUTS"
    VERIFY_MANUAL_EIP = "VERIFY MANUAL EIP"
    MANUAL_VERIFICATION = "MANUAL VERIFICATION"
    QUERY_EVRS = "QUERY EVRS"
    EHA_QUERY_RESPONSE = "EHA QUERY RESPONSE"
    EVR_QUERY_RESPONSE = "EVR QUERY RESPONSE"
    WAIT_INTERMEDIATE_RESULT = "WAIT INTERMEDIATE RESULT"
    CUSTOM_SCRIPT_INTERMEDIATE_RESULT = "CUSTOM SCRIPT INTERMEDIATE RESULT"
    CHECK_RECORDED_VALUE = "CHECK RECORDED VALUE"
    DISPATCH_COMMAND = "DISPATCH COMMAND"
    REDIS_CHECK = "REDIS CHECK"
    STORE_EXECUTION_CACHE = "STORE EXECUTION CACHE"
    RELOAD_EXECUTION_CACHE = "RELOAD EXECUTION CACHE"
    COPY_EXECUTION_STATE = "COPY EXECUTION STATE"
    TIME_VALIDATION = "TIME VALIDATION"
    STEP_EXECUTION = "STEP EXECUTION"
    STEP_EXECUTION_COMPLETE = "STEP EXECUTION COMPLETE"
    GUARD_CONDITION_EVALUATION = "GUARD CONDITION EVALUATION"
    STEP_START = "STEP START"
    STEP_ERROR = "STEP ERROR"
    STEP_END = "STEP END"
    STEP_REPORTING = "STEP REPORTING"
    REGISTER_DATA_PATH = "REGISTER DATA PATH"
    REGISTER_SESSION_ID = "REGISTER SESSION ID"
    VERIFY_EHAS = "VERIFY EHAS"
    VERIFY_EVRS = "VERIFY EVRS"
    TIME_CONVERSION = "TIME CONVERSION"
    CONVERT_VALUE = "CONVERT VALUE"
    QUERY_1553 = "QUERY 1553 BUS LOGS"
    VERIFY_BUS_1553 = "VERIFY 1553 BUS LOGS"
    START_CUSTOM_SCRIPT= "START CUSTOM SCRIPT"
    CUSTOM_SCRIPT_STATUS = "CUSTOM SCRIPT STATUS"
    SCRIPT_OUTPUT_VALIDATION = "SCRIPT_OUTPUT_VALIDATION"
    CUSTOM_SCRIPT_EXECUTION_COMPLETE = "CUSTOM SCRIPT EXECUTION COMPLETE"
    CHECK_CUSTOM_SCRIPT_STATUS = "CHECK CUSTOM SCRIPT STATUS"


# If this is true, states of step execution will be cached in Redis.
# The environment variable is set by 01_load_modules.py when used in Execution Gateway
use_execution_cache = True
HASH_TEMPLATE = 'execution_id:{}'
redis_client = None
if use_execution_cache:
    redis_host = os.environ.get('REDIS_HOST', 'exec_redis')    
    redis_port_str = os.environ.get('REDIS_PORT', '6379')
    redis_port = 6379
    try:
        redis_port = int(redis_port_str)
    except:
        msg = 'REDIS port is not an integer: {}'.format(redis_port_str)
        logger.error(msg, extra = {
            "event": EventName.REDIS_CHECK.value,
            "data": {
                "message": msg,
                "error_type": ErrorType.CONFIGURATION_ERROR.value,
                "error_source": ErrorSource.EMBEDDED_CODE.value,
                "http_code_at_source": 0
            }
        })

    redis_client = redis.StrictRedis(host=redis_host, port=redis_port)

def determine_cmd_failure(step_type, verify, entry):

    if verify:
        # if verification is turned on, then both radiated and verified must be true in order for the cmd to pass.
        return entry.get("verified") is False or entry.get("radiated") is False
    else:
        # if verification is turned off, we determine whether a command was successful by whether it was radiated.
        return entry.get("radiated") is False

def dict_digest(dict_input, keys):    
    dict_output = {}
    for key in keys:
        dict_output[key] = dict_input.get(key)
    return dict_output

def dict_digest_str(dict_input, keys):
    items = []
    for key in keys:
        value = dict_input.get(key)
        items.append('{}: {}'.format(key, value))
    return ' '.join(items)    

def get_empty_str_by_default(str_value):
    if str_value is None:
        return ''
    else:
        return str_value.decode('utf-8')    

def get_empty_dict_by_default(str_value):
    if str_value is None:
        return {}        
    else:
        return json.loads(str_value.decode('utf-8'))

def get_empty_array_by_default(str_value):
    if str_value is None:
        return [] 
    else:
        return json.loads(str_value.decode('utf-8'))        

def store_execution_cache(execution_id):
        if use_execution_cache:
            input_dict = {
                'execution_id': ic.execution_id,
                'venue_service_address': ic.venue_service_address,
                'venue_sse': ic.venue_sse,
                'venue_name': ic.venue_name,
                'venue_id': ic.venue_id,
                'venue_type': ic.venue_type,
                'ampcs_session_information': json.dumps(ic.ampcs_session_information),
                'variables': json.dumps(ic.variables),
                'environment_step_variables': json.dumps(ic.environment_step_variables),
                'manual_input_variables': json.dumps(ic.manual_input_variables),
                'channel_variables': json.dumps(ic.channel_variables),
                'cmd_variables': json.dumps(ic.cmd_variables),
                'last_step_status': ic.last_step_status,
                'time_references': json.dumps(ic.time_references),
                'ing_token': ic.ing_token,
                'venue_token': ic.venue_token,
                'run_mode': ic.run_mode,
                'mil_1553_variables': json.dumps(ic.mil_1553_variables)
            }

            exec_hash = HASH_TEMPLATE.format(execution_id)
            redis_client.hset(exec_hash, mapping=input_dict)
        else:
            logger.info('reload_execution_cache: use_execution_cache is False', extra= {
                "event": EventName.STORE_EXECUTION_CACHE.value
            })
      

def reload_execution_cache(execution_id):
    if use_execution_cache:
        keys = [
            'execution_id',
            'venue_service_address',
            'venue_sse',
            'venue_name',
            'venue_id',
            'venue_type',
            'ampcs_session_information',
            'variables',
            'environment_step_variables',
            'manual_input_variables',
            'channel_variables',
            'cmd_variables',
            'last_step_status',
            'time_references',
            'ing_token',
            'venue_token',
            'run_mode',
            'mil_1553_variables'
        ]

        exec_hash = HASH_TEMPLATE.format(execution_id)
        value_strs = redis_client.hmget(exec_hash, keys)
        
        ic.execution_id = get_empty_str_by_default(value_strs[0])
        ic.venue_service_address = get_empty_str_by_default(value_strs[1])
        ic.venue_sse = get_empty_str_by_default(value_strs[2])
        ic.venue_name = get_empty_str_by_default(value_strs[3])
        ic.venue_id = get_empty_str_by_default(value_strs[4])
        ic.venue_type = get_empty_str_by_default(value_strs[5])
        ic.ampcs_session_information = get_empty_array_by_default(value_strs[6])
        ic.variables = get_empty_dict_by_default(value_strs[7])
        ic.environment_step_variables = get_empty_dict_by_default(value_strs[8])
        ic.manual_input_variables = get_empty_dict_by_default(value_strs[9])
        ic.channel_variables = get_empty_dict_by_default(value_strs[10])
        ic.cmd_variables = get_empty_dict_by_default(value_strs[11])
        ic.last_step_status = get_empty_str_by_default(value_strs[12])
        ic.time_references = get_empty_dict_by_default(value_strs[13])
        ic.ing_token = get_empty_str_by_default(value_strs[14])
        ic.venue_token = get_empty_str_by_default(value_strs[15])
        ic.run_mode = get_empty_str_by_default(value_strs[16])
        ic.mil_1553_variables = get_empty_dict_by_default(value_strs[17])

    else:
        logger.info('reload_execution_cache: use_execution_cache is False', extra= {
            "event": EventName.RELOAD_EXECUTION_CACHE.value
        })

def store_current_step_cache(execution_id, step):
    if use_execution_cache:
        input_dict = {
            'current_step_id': step.get('elem_id', ''),
            'current_step_type': step.get('step_type', ''),
            'current_step_number': step.get('number', '')
        }

        exec_hash = HASH_TEMPLATE.format(execution_id)
        redis_client.hset(exec_hash, mapping=input_dict)
    else:
        logger.info('store_current_step_cache: use_execution_cache is False', extra= {
            "event": EventName.STORE_EXECUTION_CACHE.value
        })

def get_current_step_cache(execution_id):
    current_step_info = {}
    if use_execution_cache:
        keys = [
            'current_step_id',
            'current_step_type',
            'current_step_number',
            'custom_script_session_id'
        ]

        exec_hash = HASH_TEMPLATE.format(execution_id)
        value_strs = redis_client.hmget(exec_hash, keys)

        for i, key in enumerate(keys):
            current_step_info[key] = get_empty_str_by_default(value_strs[i])
    else:
        logger.info('get_current_step_cache: use_execution_cache is False', extra= {
            "event": EventName.RELOAD_EXECUTION_CACHE.value
        })
    return current_step_info    

def store_custom_script_session_id(execution_id, custom_script_session_id):
    exec_hash = HASH_TEMPLATE.format(execution_id)
    redis_client.hset(exec_hash, 'custom_script_session_id', custom_script_session_id)

def copy_execution_state(execution_id, target_execution_id):
        states = []
        if use_execution_cache:
            keys = [
                'execution_id',
                'ampcs_session_information',
                'variables',
                'environment_step_variables',
                'manual_input_variables',
                'channel_variables',
                'cmd_variables',
                'last_step_status',
                'time_references',
                'mil_1553_variables'
            ]

            exec_hash = HASH_TEMPLATE.format(execution_id)
            value_strs = redis_client.hmget(exec_hash, keys)

            input_dict = {
                'execution_id': target_execution_id,   # note that target_execution_id is used here
                'ampcs_session_information': json.dumps(get_empty_array_by_default(value_strs[1])),
                'variables': json.dumps(get_empty_dict_by_default(value_strs[2])),
                'environment_step_variables': json.dumps(get_empty_dict_by_default(value_strs[3])),
                'manual_input_variables': json.dumps(get_empty_dict_by_default(value_strs[4])),
                'channel_variables': json.dumps(get_empty_dict_by_default(value_strs[5])),
                'cmd_variables': json.dumps(get_empty_dict_by_default(value_strs[6])),
                'last_step_status': get_empty_str_by_default(value_strs[7]),
                'time_references': json.dumps(get_empty_dict_by_default(value_strs[8])),
                'mil_1553_variables': json.dumps(get_empty_dict_by_default(value_strs[9]))
            }         
            #logger.info('input_dict:')
            #logger.info(json.dumps(input_dict))

            target_exec_hash = HASH_TEMPLATE.format(target_execution_id)
            redis_client.hset(target_exec_hash, mapping=input_dict)

            value_strs = redis_client.hmget(target_exec_hash, keys)  
            #logger.info('value_strs:')
            #for value_str in value_strs:
            #    logger.info(type(value_str))
            #    logger.info(value_str)                      

            states.append({'name': 'execution_id', 'value': get_empty_str_by_default(value_strs[0])})
            states.append({'name': 'ampcs_session_information', 'value': get_empty_array_by_default(value_strs[1])})
            states.append({'name': 'variables', 'value': get_empty_dict_by_default(value_strs[2])})
            states.append({'name': 'environment_step_variables', 'value': get_empty_dict_by_default(value_strs[3])})
            states.append({'name': 'manual_input_variables', 'value': get_empty_dict_by_default(value_strs[4])})
            states.append({'name': 'channel_variables', 'value': get_empty_dict_by_default(value_strs[5])})
            states.append({'name': 'cmd_variables', 'value': get_empty_dict_by_default(value_strs[6])})
            states.append({'name': 'last_step_status', 'value': get_empty_str_by_default(value_strs[7])})
            states.append({'name': 'time_references', 'value': get_empty_dict_by_default(value_strs[8])})
            states.append({'name': 'mil_1553_variables', 'value': get_empty_dict_by_default(value_strs[9])})
        else:
            logger.info('copy_execution_state: use_execution_cache is False', extra= {
                "event": EventName.COPY_EXECUTION_STATE.value
            })

        return states

def wait_execution_switch(execution_id):
    key = f'{EXECUTION_SWITCH_WAIT}:{execution_id}'
    execution_switch_wait = redis_client.get(key)
    try:
        if execution_switch_wait is None:
            execution_switch_wait = int(EXECUTION_SWITCH_WAIT_SEC)
        else:
            execution_switch_wait = int(execution_switch_wait)
    except:
        execution_switch_wait = 10

    flag_key = f'{EXECUTION_SWITCH_WAIT_FLAG}:{execution_id}'
    time_stemp = get_now_utc()
    
    if execution_switch_wait > 0:
        # set flag_key with time_stamp, and the value will expire after execution_switch_wait secs.
        # flag_key may be cleared by UI or expire.
        redis_client.set(flag_key, time_stemp, ex=execution_switch_wait)
    
        value = redis_client.get(flag_key)
        while value is not None:
            logger.debug(f'wait for execution switch completion: {execution_id}')
            time.sleep(1)
            value = redis_client.get(flag_key)

class StepExecutionError(Exception):
    def __init__(self, message, error_obj):

        # Call the base class constructor with the parameters it needs
        super(StepExecutionError, self).__init__(message)

        # Now for your custom code...
        self.error_obj = error_obj

########### Functions

# API endpoints are retrieved by calling a function listed below.

def get_eha_realtime_url():
    return '{}/api/{}/eha/realtime'.format(ic.venue_service_address, ic.venue_service_version)

def get_eha_realtime_multi_url():
    return '{}/api/{}/eha/realtime_multi'.format(ic.venue_service_address, ic.venue_service_version)

def get_evr_realtime_url():
    return '{}/api/{}/evr/realtime'.format(ic.venue_service_address, ic.venue_service_version)

def get_venue_configurations_url():
    # Venue Config Service is running inside container. By default, use the container/service name.
    # If Venue Config Service is running outside container, need to set VENUE_CONFIG_SERVER env variable.
    venue_config_server = os.environ.get('VENUE_CONFIG_SERVER', 'http://venue_config:5151')
    return "{}/api/{}/configurations".format(venue_config_server, ic.venue_config_version)

def get_eha_chill_url():
    return "{}/api/{}/eha/chill".format(ic.venue_service_address, ic.venue_service_version)

def get_evr_chill_url():
    return "{}/api/{}/evr/chill".format(ic.venue_service_address, ic.venue_service_version)

def get_cmd_url():
    return "{}/api/{}/cmd".format(ic.venue_service_address, ic.venue_service_version)

def get_mtak_url():
    return "{}/api/{}/mtak".format(ic.venue_service_address, ic.venue_service_version)

def get_dp_url():
    return "{}/api/{}/dp".format(ic.venue_service_address, ic.venue_service_version)

def get_query_1553_url():
    return "{}/api/{}/bus1553".format(ic.venue_service_address, ic.venue_service_version)

def get_custom_script_start_url():
    return "{}/api/{}/custom_script/start".format(ic.venue_service_address, ic.venue_service_version)

def get_custom_script_status_url():
    return "{}/api/{}/custom_script".format(ic.venue_service_address, ic.venue_service_version)

def halt_custom_script_url():
    return "{}/api/{}/custom_script".format(ic.venue_service_address, ic.venue_service_version)
  

# Venue Simulator /test endpoints

def get_forced_errors():
    return "{}/api/{}/test/forced_errors".format(ic.venue_service_address, ic.venue_service_version)

def get_test_eha():
    return "{}/api/{}/test/eha".format(ic.venue_service_address, ic.venue_service_version)

def get_test_evr():
    return "{}/api/{}/test/evr".format(ic.venue_service_address, ic.venue_service_version)

def get_test_dp():
    return "{}/api/{}/test/dp".format(ic.venue_service_address, ic.venue_service_version)

def get_receipt_configs():
    return "{}/api/{}/test/receipt_configs".format(ic.venue_service_address, ic.venue_service_version)

def get_scmf_config():
    return "{}/api/{}/test/scmf_config".format(ic.venue_service_address, ic.venue_service_version)

def post_1553_test_data():
    return "{}/api/{}/test/bus_1553".format(ic.venue_service_address, ic.venue_service_version)

def post_test_script_status():
    return "{}/api/{}/test/custom_script_status".format(ic.venue_service_address, ic.venue_service_version)

def get_custom_script_tar(logfile_partial_url):
    path_base = "{}/api/{}".format(ic.venue_service_address, ic.venue_service_version)
    final_path = os.path.join(path_base, logfile_partial_url)
    return final_path

def convert_time(time):
    """
    This function will attempt to parse the provided time and will return either a datetime object if
    successful (depending on format).
    """

    try:
        return datetime.strptime(time,"%Y-%jT%H:%M:%S.%f")
    except:
        pass

    try:
        return datetime.strptime(time,"%Y-%jT%H:%M:%S")
    except:
        pass

    try:
        return datetime.strptime(time,"%Y-%m-%dT%H:%M:%S")
    except:
        pass

    try:
        return datetime.strptime(time,"%Y-%m-%dT%H:%M:%S.%fZ")
    except:
        pass

    try:
        return datetime.strptime(time,"%Y-%m-%dT%H:%M:%S.%f")
    except:
        pass

    msg = "ERROR: The time provided (%s) could not be understood. Try standard ISO (YEAR-MONTH-DAYTHOUR:MIN:SEC) or DOY formats (YEAR-DOYTHOUR:MIN:SEC) " % time
    # log statement
    logger.error(msg, extra = {
        "event": EventName.TIME_CONVERSION.value,
        "data": {
            "message": msg,
            "error_type": ErrorType.USER_INPUT_ERROR.value,
            "error_source": ErrorSource.EMBEDDED_CODE.value,
            "http_code_at_source": 0
        }
    })
    error_obj = create_step_error(message=msg,
                    details=[],
                    error_type=ErrorType.USER_INPUT_ERROR.value,
                    error_source=ErrorSource.EMBEDDED_CODE.value,
                    http_code_at_source=0)
    raise StepExecutionError(msg, error_obj)


# grabs the current time, formats the time and returns it.
def get_now_utc():
    """
    Get the current date and time in the following format:

    2017-09-01T17:07:37.989Z
    """
    time_now = datetime.utcnow()

    return to_utc_str(time_now)

# converts python datetime object to a formatted string
def to_utc_str(datetime_obj):
    down_to_micro_sec = datetime.strftime(datetime_obj, '%Y-%m-%dT%H:%M:%S.%f')
    
    down_to_mili_sec = down_to_micro_sec[:-3]
    
    return down_to_mili_sec + 'Z'   


def record_step_start_end_times(step_type, time_started, time_completed):
    ic.time_references['LAST_STEP_START'] = time_started
    ic.time_references['LAST_STEP_END'] = time_completed

    if step_type == 'CMD':
        ic.time_references['LAST_FSW_CMD_STEP_START'] = time_started
        ic.time_references['LAST_FSW_CMD_STEP_END'] = time_completed
    elif step_type == 'CMD_SSE':
        ic.time_references['LAST_SSE_CMD_STEP_START'] = time_started
        ic.time_references['LAST_SSE_CMD_STEP_END'] = time_completed
    elif step_type == 'CMD_FILE':
        ic.time_references['LAST_CMD_FILE_STEP_START'] = time_started
        ic.time_references['LAST_CMD_FILE_STEP_END'] = time_completed
    elif step_type == 'CMD_SCMF':
        ic.time_references['LAST_CMD_SCMF_FILE_STEP_START'] = time_started
        ic.time_references['LAST_CMD_SCMF_FILE_STEP_END'] = time_completed
    elif step_type == 'CUSTOM_SCRIPT':
        ic.time_references['LAST_CUSTOM_SCRIPT_STEP_START'] = time_started
        ic.time_references['LAST_CUSTOM_SCRIPT_STEP_END'] = time_completed

# return a value of a dictionary. Return None if the value is a whitespace only string
def get_dict_value_default_none(dict_obj, key):
    value = dict_obj.get(key)

    if type(value) == str:
        value_trimmed = value.strip()
        if value_trimmed == '':
            return None
        else:
            return value
    else:
        return value

def get_dict_value(dict_obj, key, default_value):
    value = dict_obj.get(key, default_value)

    if type(value) == str:
        value_trimmed = value.strip()
        if value_trimmed == '':
            return default_value
        else:
            return value
    else:
        return value


def create_step_error(message='Error in embedded code',
                   details=[],
                   error_type=ErrorType.INGENIUM_SERVICE_ERROR.value,
                   error_source=ErrorSource.EMBEDDED_CODE.value,
                   http_code_at_source=0):

    return {
        'message': message,
        'details': details,
        'error_type': error_type,
        'error_source': error_source,
        'http_code_at_source': http_code_at_source
    }

def return_step_with_error(step, error_obj):
    step['execution']['meta_data']['status'] = 'ERROR'
    step['execution']['meta_data']['error'] = error_obj
    return step


# The return value is a datetime string
def get_reference_time(name):
    if name == "CURRENT_STEP_START" or name == "CURRENT_TIME":
        return get_now_utc()
    else:
        return ic.time_references.get(name, '')


def get_telemetry_query_time(timeout, time_input=None):
    
    if time_input is None:
        # start time is now time (UTC) if a time input is not set.
        start_time = datetime.utcnow()
    else:
        start_time = datetime.strptime(time_input, "%Y-%m-%dT%H:%M:%S.%fZ")

    # end time is start time plus timeout
    end_time = start_time + timedelta(seconds=int(timeout))

    start_formatted_time = datetime.strftime(start_time, "%Y-%jT%H:%M:%S")
    end_formatted_time = datetime.strftime(end_time, "%Y-%jT%H:%M:%S")

    return start_formatted_time, end_formatted_time   

def determine_actual_value(entry, eha_response):

    dn_eu = entry["dn_eu"].lower()

    # EU = EU for numerics, Status for Enum/Bool
    if dn_eu == "eu":
        if eha_response["channelType"] in ["ASCII"]:
            msg = "ASCII channel type does not have an EU value."
            error_obj = create_step_error(message=msg,
                                details=[],
                                error_type=ErrorType.USER_INPUT_ERROR.value,
                                error_source=ErrorSource.EMBEDDED_CODE.value,
                                http_code_at_source=0)
            logger.error(msg, extra = {
                "event": EventName.USER_INPUT_VALIDATION.value,
                "data": error_obj
            })
            raise StepExecutionError(msg, error_obj)

        elif eha_response["channelType"] in ["STATUS", "BOOLEAN"]:
            eha_response["actual_value"] = eha_response["channelStatus"]
            value_type= "STRING"
        else:
            # Evaluate EU as float
            eha_response["actual_value"] = float(eha_response[dn_eu])
            value_type = "FLOAT"
    elif dn_eu == "dn":
        if eha_response["channelType"] == "FLOAT":
            eha_response["actual_value"] = float(eha_response[dn_eu])
            value_type = "FLOAT"
        elif eha_response["channelType"] == "ASCII":
            eha_response["actual_value"] = eha_response[dn_eu]
            value_type = "STRING"
        elif eha_response["channelType"] in ["UNSIGNED_INT", "SIGNED_INT", "TIME", "BOOLEAN", "STATUS"]:
            eha_response["actual_value"] = int(eha_response[dn_eu])
            value_type = "INTEGER"
        else:
            # catch all case  (UNKNOWN?, DIGITAL?)
            eha_response["actual_value"] = eha_response[dn_eu]
            value_type = "STRING"
        
    return eha_response, value_type

def record_channel_data(entry):
    channel_id = entry.get("channel_id")
    data_path = entry.get("data_path")

    if channel_id is not None and data_path is not None:
        try:
            session = get_session_information(data_path)
            channel_key = f"{session}:{channel_id}"
            ic.channel_variables[channel_key] = entry
        except Exception as ex:
            msg = f"Failed to record channel data. data_path: {data_path} channel_id: {channel_id} details: {str(ex)}"
            logger.warning(msg)
    else:
        msg = f"Cannot record channel data. data_path: {data_path} channel_id: {channel_id}"
        logger.warning(msg)

def record_bus_1553_data(entry):

    bus_name = entry["bus_1553_var"]
    ic.mil_1553_variables[bus_name] = entry

def ing_profile(log_level):
    """    
    Decorator to log start and end of function calls.
    """
    def ing_profile_internal(some_function):
        def wrapper(*args, **kwargs):

            results = None

            time0 = time.time()

            try:
                results = some_function(*args, **kwargs)
            except:
                time1 = time.time()
                elapsed_sec = time1 - time0
                msg = "{} failed. elapsed_sec = {}".format(some_function.__name__, elapsed_sec)
                # log statement
                logger.error(msg, extra = {
                    "event": EventName.STEP_EXECUTION.value,
                    "data": {
                        "message": msg,
                        "error_type": ErrorType.STEP_ERROR.value,
                        "error_source": ErrorSource.EMBEDDED_CODE.value,
                        "http_code_at_source": 0,
                        "details": [traceback.format_exc()]
                    }
                })
                # simply raise. This will preserve the call stack of the original exception
                raise
            else:
                time1 = time.time()
                elapsed_sec = time1 - time0
                msg = "{} ended. elapsed_sec = {}".format(some_function.__name__, elapsed_sec)
                logger.info(msg, extra={
                    "event": EventName.STEP_EXECUTION_COMPLETE.value
                })

            return results
        return wrapper
    return ing_profile_internal

def check_guard(step):
    guard = step.get('guard')
    guard_passed = True
    step_type = step['step_type']

    if (guard is None or guard.strip() == ""):
        pass
    else:
        # evaluate guard

        # TODO: implement evaluation guard.
        # This will involve evaluate the guard expression against the current variables.

        # guard_passed = True

        if guard_passed:
            msg = "Guard condition was met."
            logger.info(msg, extra={
                "event": EventName.GUARD_CONDITION_EVALUATION.value
            })
        else:
            msg = "{} - Guard condition was not met. Skip execution.".format(step_type)
            logger.info(msg, extra={
                "event": EventName.GUARD_CONDITION_EVALUATION.value
            })
            step['execution']['meta_data']['status'] = 'SKIPPED'
    return guard_passed

def report_step_results(step, step_execution, error_msg):
    execution_id = step.get('execution_id')
    elem_id = step.get('elem_id')
    return report_step_results2(execution_id, elem_id, step_execution, error_msg)

def report_step_results2(execution_id, elem_id, step_execution, error_msg):
    
    refresh_ingenium_token()
    header = get_ing_authorization_header()

    core_server = os.environ.get('CORE_SERVER', 'http://core_server:8080')

    url = '{}/api/{}/executions/{}/steps/{}/result'.format(core_server, ic.core_service_version, execution_id, elem_id)

    step_status = step_execution['meta_data'].get('status')

    time_updated = get_now_utc()
    step_execution['meta_data']['time_updated'] = time_updated
    if step_status == 'PASS' or step_status == 'FAIL' or step_status == 'ERROR':
        step_execution['meta_data']['time_completed'] = time_updated

    # reset status_message if it was not provided
    if 'status_message' not in step_execution['meta_data']:
        step_execution['meta_data']['status_message'] = ''

    if error_msg:
        # set status to ERROR only when status was not set
        if step_status is None:
            step_execution['meta_data']['status'] = 'ERROR'
        
        err_dict = {'message': error_msg,
                    'details': [],
                    'error_type': ErrorType.INGENIUM_SERVICE_ERROR.value,
                    'error_source': ErrorSource.EMBEDDED_CODE.value,
                    'http_code_at_source': 0}

        step_execution['meta_data']['error'] = err_dict     

    res = requests.post(url, json=step_execution, headers=header)
    if res.status_code == 200:
        return res.json()
    else:
        error_msg = "Failed to send step results to Core."
        logger.error(error_msg, extra = {
            "event": EventName.STEP_ERROR.value,
            "data": {
                "message": error_msg,
                "error_type": ErrorType.INGENIUM_SERVICE_ERROR.value,
                "error_source": ErrorSource.EMBEDDED_CODE.value,
                "http_code_at_source": res.status_code,
                "details": [res.text]
            }
        })

def update_execution(execution_id, execution_input):    
    refresh_ingenium_token()
    header = get_ing_authorization_header()

    core_server = os.environ.get('CORE_SERVER', 'http://core_server:8080')

    url = '{}/api/{}/executions/{}'.format(core_server, ic.core_service_version, execution_id)

    res = requests.patch(url, json=execution_input, headers=header)
    if res.status_code == 200:
        return res.json()
    else:
        error_msg = "Failed to update execution"
        logger.error(error_msg, extra = {
            "event": EventName.STEP_ERROR.value,
            "data": {
                "message": error_msg,
                "error_type": ErrorType.INGENIUM_SERVICE_ERROR.value,
                "error_source": ErrorSource.EMBEDDED_CODE.value,
                "http_code_at_source": res.status_code,
                "details": [res.text]
            }
        })
        return None

def get_execution(execution_id):    
    refresh_ingenium_token()
    header = get_ing_authorization_header()

    core_server = os.environ.get('CORE_SERVER', 'http://core_server:8080')

    url = '{}/api/{}/executions/{}'.format(core_server, ic.core_service_version, execution_id)

    res = requests.get(url, headers=header)
    if res.status_code == 200:
        return res.json(), None
    else:
        error_msg = f'Failed to get execution. execution_id: {execution_id} details: {res.text}'
        return None, error_msg

def get_element(execution_id, elem_id):    
    refresh_ingenium_token()
    header = get_ing_authorization_header()

    core_server = os.environ.get('CORE_SERVER', 'http://core_server:8080')

    url = '{}/api/{}/executions/{}/steps/{}'.format(core_server, ic.core_service_version, execution_id, elem_id)
    res = requests.get(url, headers=header)
    if res.status_code == 200:
        return res.json(), None
    else:
        error_msg = f'Failed to get execution element. execution_id: {execution_id} elem_id: {elem_id} status_code: {res.status_code} details: {res.text}'
        return None, error_msg

def get_simple_elements(execution_id):    
    refresh_ingenium_token()
    header = get_ing_authorization_header()

    core_server = os.environ.get('CORE_SERVER', 'http://core_server:8080')

    url = '{}/api/{}/executions/{}/simple_elements'.format(core_server, ic.core_service_version, execution_id)

    res = requests.get(url, headers=header)
    if res.status_code == 200:
        return res.json(), None
    else:
        error_msg = f'Failed to get execution simple elements. execution_id: {execution_id} status_code: {res.status_code} details: {res.text}'
        return None, error_msg

def get_execution_step(execution_id, elem_id):    
    refresh_ingenium_token()
    header = get_ing_authorization_header()

    core_server = os.environ.get('CORE_SERVER', 'http://core_server:8080')

    url = '{}/api/{}/executions/{}/steps/{}'.format(core_server, ic.core_service_version, execution_id, elem_id)

    res = requests.get(url, headers=header)
    if res.status_code == 200:
        return res.json(), None
    else:
        error_msg = f'Failed to get step. execution_id: {execution_id} elem_id: {elem_id} details: {res.text}'
        return None, error_msg

def compute_step(execution_id, elem_id):    
    refresh_ingenium_token()
    header = get_ing_authorization_header()

    core_server = os.environ.get('CORE_SERVER', 'http://core_server:8080')

    url = '{}/api/{}/executions/{}/elements/{}/compute'.format(core_server, ic.core_service_version, execution_id, elem_id)

    res = requests.post(url, headers=header)
    if res.status_code == 200:
        return res.json(), None
    else:
        error_msg = f'Failed to compute a step. execution_id: {execution_id} elem_id: {elem_id} details: {res.text}'
        return None, error_msg

def create_new_run(execution_id, elem_id):    
    refresh_ingenium_token()
    header = get_ing_authorization_header()

    core_server = os.environ.get('CORE_SERVER', 'http://core_server:8080')

    url = '{}/api/{}/executions/{}/steps/{}/new_run'.format(core_server, ic.core_service_version, execution_id, elem_id)

    res = requests.post(url, headers=header)
    if res.status_code == 200:
        return res.json(), None
    else:
        error_msg = f'Failed to create a new run. execution_id: {execution_id} elem_id: {elem_id} details: {res.text}'
        return None, error_msg

def import_procedure_section(execution_id, elem_id):
    refresh_ingenium_token()
    header = get_ing_authorization_header()

    core_server = os.environ.get('CORE_SERVER', 'http://core_server:8080')

    url = '{}/api/{}/executions/{}/procedure_sections/{}/import'.format(core_server, ic.core_service_version, execution_id, elem_id)

    res = requests.post(url, headers=header)
    if res.status_code == 200:
        return res.json(), None
    else:
        error_msg = f'Failed to import a procedure. execution_id: {execution_id} elem_id: {elem_id} details: {res.text}'
        return None, error_msg

def call_procedure_section(execution_id, elem_id):
    refresh_ingenium_token()
    header = get_ing_authorization_header()

    core_server = os.environ.get('CORE_SERVER', 'http://core_server:8080')

    url = '{}/api/{}/executions/{}/procedure_sections/{}/call'.format(core_server, ic.core_service_version, execution_id, elem_id)

    res = requests.post(url, headers=header)
    if res.status_code == 200:
        return res.json(), None
    else:
        error_msg = f'Failed to call a procedure. execution_id: {execution_id} elem_id: {elem_id} details: {res.text}'
        return None, error_msg

def switch_execution(execution_id, target_execution_id):
    refresh_ingenium_token()
    header = get_ing_authorization_header()

    exec_server = os.environ.get('EXECUTION_SERVER', 'http://exec_server:9999')

    url = '{}/api/{}/executions/{}/switch'.format(exec_server, ic.exec_server_version, execution_id)
    res = requests.post(url, params={'target_execution_id': target_execution_id}, headers=header)
    if res.status_code == 204:
        return None, None
    else:
        error_msg = f'Failed to switch execution. execution_id: {execution_id} target_execution_id: {target_execution_id} status_code: {res.status_code} details: {res.text}'
        return None, error_msg

def suspend_resume_execution(execution_id, target_execution_id):
    refresh_ingenium_token()
    header = get_ing_authorization_header()

    core_server = os.environ.get('CORE_SERVER', 'http://core_server:8080')

    url = '{}/api/{}/executions/{}/suspend_resume'.format(core_server, ic.core_service_version, execution_id)
    suspend_resume_input = {
        'target_execution_id': target_execution_id
    }
    res = requests.post(url, json=suspend_resume_input, headers=header)
    if res.status_code == 200:
        return res.json(), None
    else:
        error_msg = f'Failed to suspend and resume. execution_id: {execution_id} target_execution_id: {target_execution_id} details: {res.text}'
        return None, error_msg

def post_execution_message(execution_id, level, msg):
    refresh_ingenium_token()
    header = get_ing_authorization_header()

    core_server = os.environ.get('CORE_SERVER', 'http://core_server:8080')

    url = '{}/api/{}/executions/{}/message'.format(core_server, ic.core_service_version, execution_id)
    execution_message = {
        'level': level,
        'msg': msg
    }
    logger.debug(msg)
    res = requests.post(url, json=execution_message, headers=header)
    if res.status_code != 204:
        error_msg = f'Failed to post execution message. execution_id: {execution_id} level: {level} msg: {msg}'
        logger.warning(error_msg)


def handle_execution_error(execution_id, elem_id, error_msg):
    results = {
        'meta_data': {
            'status': 'ERROR'
        }
    }
    report_step_results2(execution_id, elem_id, results, error_msg)

    update_execution(execution_id, {'status': 'IDLE'})
    
def ing_execution(run_function):
    def wrapper(step):
        error_msg = None
        variable_name = None
        step_output = None        

        execution_id = step.get('execution_id', '')
        number = step.get('number', '')
        elem_id = step.get('elem_id', '')

        try:
            digest_keys = ['execution_id', 'procedure_id', 'number', 'step_type', 'title', 'elem_id']
            step_digest = dict_digest(step, digest_keys)
            step_digest_str = dict_digest_str(step, digest_keys)

            store_current_step_cache(execution_id, step)

            variable = step.get('variable')
            if variable is not None:
                variable_name = variable.get('name')

            # check guard condition
            try:
                if not check_guard(step):
                    return step
            except:
                error_msg = "Failed to evaluate guard condition."
                # log statement
                logger.error(error_msg, extra = {
                    "event": EventName.GUARD_CONDITION_EVALUATION.value,
                    "data": {
                        "message": error_msg,
                        "error_type": ErrorType.CONDITION_EVALUATION_ERROR.value,
                        "error_source": ErrorSource.EMBEDDED_CODE.value,
                        "http_code_at_source": 0,
                        "details": [traceback.format_exc()]
                    }
                })
                # simply raise. This will keep the stack trace of the original error
                raise

            # Run step
            try:
                time0 = time.time()
                if ic.run_mode == 'ASYNC':
                    execution_start_msg = {'meta_data': {'status': 'RUNNING', 'status_message': 'Step started'}}
                    # log statement
                    logger.info(f"step started. execution_id: {execution_id} number: {number} elem_id: {elem_id}", extra = {
                        "event": EventName.STEP_START.value,
                        "data": step_digest
                    })
                    report_step_results(step, execution_start_msg, None)   
                step_output = run_function(step)

            except:
                time1 = time.time()
                elapsed_sec = time1 - time0
                error_msg = 'step failed. elapsed_sec: {} {}'.format(elapsed_sec, step_digest_str)
                # log statement
                logger.error(error_msg, extra = {
                    "event": EventName.STEP_ERROR.value,
                    "data": {
                        "message": error_msg,
                        "error_type": ErrorType.STEP_ERROR.value,
                        "error_source": ErrorSource.EMBEDDED_CODE.value,
                        "http_code_at_source": 0,
                        "details": [traceback.format_exc()]
                    }
                })

                # simply raise. This will keep the stack trace of the original error
                raise
            else:
                time1 = time.time()
                elapsed_sec = time1 - time0

                # set variable of the step execution results
                # HK: I think this is used only for tests currently. To be revisited when we support execution level state variables.
                if variable_name is not None:
                    if step_output.get('execution') is not None:
                        ic.variables[variable_name] = step_output.get('execution').get('results')

            return step_output

        finally:
            # time_started was already set by execution server
            try:
                time_started = step['execution']['meta_data']['time_started']
                time_completed = get_now_utc()
                record_step_start_end_times(step['step_type'], time_started, time_completed)
                store_execution_cache(execution_id)

                if step_output:
                    step_execution = step_output['execution']
                else:     
                    step_execution = step['execution']

                step_execution['meta_data']['time_completed'] = time_completed
                step_execution['meta_data']['time_updated'] = time_completed

                # log statement
                step_digest["status"] = step_execution['meta_data'].get("status")
                logger.info(f"step completed. execution_id: {execution_id} number: {number} elem_id: {elem_id}", extra = {
                    "event": EventName.STEP_END.value,
                    "data": step_digest
                })

                if ic.run_mode == 'ASYNC':
                    report_step_results(step, step_execution, error_msg)
            except:
                error_msg = 'Reporting failed'
                # log statement
                logger.error(error_msg, extra = {
                    "event": EventName.STEP_REPORTING.value,
                    "data": {
                        "message": error_msg,
                        "error_type": ErrorType.REPORTING_ERROR.value,
                        "error_source": ErrorSource.EMBEDDED_CODE.value,
                        "http_code_at_source": 0,
                        "details": [traceback.format_exc()]
                    }
                })
            
    return wrapper


def determine_response(endpoint_name, query_response, body_data=None):
    '''
    This function uses the status code from a query request to determine whether the call was successful.
    If the response is an error, it will raise an Exception. In all cases, logger will output a message
    to the console.

    Add a status code as an elif statement if you need more specific responses to a specific status code.

    params:
    - endpoint_name: Provide a string noting what api endpoint was invoked. This will allow for more helpful logging
                as well as assisting in diagnosing where an error originated.
    - query_response: Provide the entire request object. This function will invoke the "status_code" property of the
                      response object.
    - body_data: body data will allow for inspecting the parameters used in a faulty api reqest.

    '''

    #TODO add path and exception traceback into log message

    status_code = query_response.status_code

    if status_code == 200:
        msg = "{} query was successful".format(endpoint_name)

    elif status_code == 400:
        msg = "{} - Bad Request".format(endpoint_name)

    elif status_code == 401:
        msg = "{} - Unauthorized - invalid token".format(endpoint_name)

    elif status_code == 403:
        msg = "{} - Unauthorized - insufficient permission".format(endpoint_name)

    elif status_code == 404:
        msg = "{} - Resource was not found".format(endpoint_name)

    elif status_code == 408:
        msg = "{} - Time out".format(endpoint_name)

    elif status_code in range(500, 599):
        msg = "{} - Server Error".format(endpoint_name)

def get_session_information(data_path):

    session = None
    
    if data_path is not None:
        data_path = data_path.strip()
        for dp in ic.ampcs_session_information:
            if dp.get("data_path") == data_path:
                session = dp.get("session_id")
                return session

    if not session:
        msg = "Attempted to relate data_path: {} to a session and was unsuccessful. Defined data_paths include: {}".format(data_path, ic.ampcs_session_information)
        # log statement
        logger.error(msg, extra = {
            "event": EventName.REGISTER_DATA_PATH.value,
            "data": {
                "message": msg,
                "error_type": ErrorType.CANNOT_RELATE_DATA_PATH.value,
                "error_source": ErrorSource.EMBEDDED_CODE.value,
                "http_code_at_source": 0
            }
        })
        raise Exception(msg)

def validate_times(execution_input, step_type):
    '''
    This function validates the times provided by the end user and either raises and exception or returns a standard
    set of times to be used in queries. 
    Time validation can take one of two forms. The time form is determined by the time_type

    :param execution_input: execution time input
    :param step_type: step type
        
    :return: (translated_start_time, translated_end_time, start_time, end_time) in string format. The format may be DOY for ERT/SCET or integer in string for SCLK
    '''

    translated_start_time = ''
    translated_end_time = ''

    if step_type in ['VERIFY_EHA', 'WAIT_EHA', 'WAIT_EVR', 'BUS_1553', 'WAIT_DATA_PRODUCTS']:
        # timeout is used to calculate query end time and also only as the timeout of REST call to venue server.
        include_timeout = True
    elif step_type in ['QUERY_EVR', 'LIST_DATA_PRODUCTS', 'GRAPH_EHA']:
        # timeout is used only as the timeout of REST call to venue server.
        include_timeout = False
    else:
        msg = "Unrecognized step type: %s" % step_type
        # log statement
        logger.error(msg, extra = {
            "event": EventName.TIME_VALIDATION.value,
            "data": {
                "message": msg,
                "error_type": ErrorType.INGENIUM_SERVICE_ERROR.value,
                "error_source": ErrorSource.EMBEDDED_CODE.value,
                "http_code_at_source": 0,
                "details": []
            }
        })
        error_obj = create_step_error(message=msg,
                            details=[],
                            error_type=ErrorType.USER_INPUT_ERROR.value,
                            error_source=ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)
        raise StepExecutionError(msg, error_obj)

    start_time = execution_input.get('start_time')
    end_time = execution_input.get('end_time')
    # WaitEVR step has no time_type. Consider as ERT
    time_type = execution_input.get('time_type', 'ERT')
    duration = execution_input.get('duration')
    lookback = execution_input.get('lookback')
    timeout = execution_input.get('timeout')

    if (not start_time) and (not end_time):
        msg = "start_time and end_time were not specified."
        # log statement
        logger.error(msg, extra = {
            "event": EventName.TIME_VALIDATION.value,
            "data": {
                "message": msg,
                "error_type": ErrorType.USER_INPUT_ERROR.value,
                "error_source": ErrorSource.EMBEDDED_CODE.value,
                "http_code_at_source": 0,
                "details": []
            }
        })
        error_obj = create_step_error(message=msg,
                            details=[],
                            error_type=ErrorType.USER_INPUT_ERROR.value,
                            error_source=ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)
        raise StepExecutionError(msg, error_obj)

    # Check if the start time is provided - if so check it and make it either an int (SCLK) or a datetime object (SCET,ERT)
    if start_time:
        # Check if the start time is one of the reference time (if so, translate it)
        translated_start_time = get_reference_time(start_time)
        if translated_start_time:
            # time type of BUS_1553 can be set as ERT or SCLK, while it is actually ERT.
            if time_type != "ERT" and step_type != "BUS_1553":
                msg = f"Time reference ({start_time}) of start time cannot be used with {time_type}. Time type must be ERT."

                # log statement
                logger.error(msg, extra = {
                    "event": EventName.TIME_VALIDATION.value,
                    "data": {
                        "message": msg,
                        "error_type": ErrorType.USER_INPUT_ERROR.value,
                        "error_source": ErrorSource.EMBEDDED_CODE.value,
                        "http_code_at_source": 0,
                        "details": []
                    }
                })
                error_obj = create_step_error(message=msg,
                                    details=[],
                                    error_type=ErrorType.USER_INPUT_ERROR.value,
                                    error_source=ErrorSource.EMBEDDED_CODE.value,
                                    http_code_at_source=0)
                raise StepExecutionError(msg, error_obj)
            else:
                start_time = convert_time(translated_start_time)
        elif time_type in ['SCET','ERT']:
            try:
                start_time=convert_time(start_time)
            except:
                msg = "Could not parse start time: {} time type: {}".format(start_time, time_type)
                # log statement
                logger.error(msg, extra = {
                    "event": EventName.TIME_VALIDATION.value,
                    "data": {
                        "message": msg,
                        "error_type": ErrorType.USER_INPUT_ERROR.value,
                        "error_source": ErrorSource.EMBEDDED_CODE.value,
                        "http_code_at_source": 0,
                        "details": []
                    }
                })
                error_obj = create_step_error(message=msg,
                                    details=[],
                                    error_type=ErrorType.USER_INPUT_ERROR.value,
                                    error_source=ErrorSource.EMBEDDED_CODE.value,
                                    http_code_at_source=0)
                raise StepExecutionError(msg, error_obj)

        elif time_type == 'SCLK':
            try:
                start_time=int(start_time)
            except:
                msg = "Start time: {} with a time type of {} must be represented as an integer.".format(start_time, time_type)
                # log statement
                logger.error(msg, extra = {
                    "event": EventName.TIME_VALIDATION.value,
                    "data": {
                        "message": msg,
                        "error_type": ErrorType.USER_INPUT_ERROR.value,
                        "error_source": ErrorSource.EMBEDDED_CODE.value,
                        "http_code_at_source": 0,
                        "details": []
                    }
                })
                error_obj = create_step_error(message=msg,
                                    details=[],
                                    error_type=ErrorType.USER_INPUT_ERROR.value,
                                    error_source=ErrorSource.EMBEDDED_CODE.value,
                                    http_code_at_source=0)
                raise StepExecutionError(msg, error_obj)

    # Check if the end time is provided- if so check it and make it either an int (SCLK) or a datetime object (SCET,ERT)
    if end_time:
        # Check if the start time is one of the reference times (if so, translate it)
        translated_end_time = get_reference_time(end_time)
        if translated_end_time:
            # time type of BUS_1553 can be set as ERT or SCLK, while it is actually ERT.
            if time_type != "ERT" and step_type != "BUS_1553":
                msg = f"Time reference ({end_time}) of end time cannot be used with {time_type}. Time type must be ERT."
                # log statement
                logger.error(msg, extra = {
                    "event": EventName.TIME_VALIDATION.value,
                    "data": {
                        "message": msg,
                        "error_type": ErrorType.USER_INPUT_ERROR.value,
                        "error_source": ErrorSource.EMBEDDED_CODE.value,
                        "http_code_at_source": 0,
                        "details": []
                    }
                })
                error_obj = create_step_error(message=msg,
                                    details=[],
                                    error_type=ErrorType.USER_INPUT_ERROR.value,
                                    error_source=ErrorSource.EMBEDDED_CODE.value,
                                    http_code_at_source=0)
                raise StepExecutionError(msg, error_obj)
            else:
                end_time = convert_time(translated_end_time)

        elif time_type in ['SCET','ERT']:
            try:
                end_time = convert_time(end_time)
            except:
                msg = "Could not parse end time: {} time type: {}".format(end_time, time_type)
                # log statement
                logger.error(msg, extra = {
                    "event": EventName.TIME_VALIDATION.value,
                    "data": {
                        "message": msg,
                        "error_type": ErrorType.USER_INPUT_ERROR.value,
                        "error_source": ErrorSource.EMBEDDED_CODE.value,
                        "http_code_at_source": 0,
                        "details": []
                    }
                })
                error_obj = create_step_error(message=msg,
                                    details=[],
                                    error_type=ErrorType.USER_INPUT_ERROR.value,
                                    error_source=ErrorSource.EMBEDDED_CODE.value,
                                    http_code_at_source=0)
                raise StepExecutionError(msg, error_obj)

        elif time_type == 'SCLK':
            try:
                end_time=int(end_time)
            except:
                msg = "Start time: {} with a time type of {} must be represented as an integer.".format(end_time, time_type)
                # log statement
                logger.error(msg, extra = {
                    "event": EventName.TIME_VALIDATION.value,
                    "data": {
                        "message": msg,
                        "error_type": ErrorType.USER_INPUT_ERROR.value,
                        "error_source": ErrorSource.EMBEDDED_CODE.value,
                        "http_code_at_source": 0,
                        "details": []
                    }
                })
                error_obj = create_step_error(message=msg,
                                    details=[],
                                    error_type=ErrorType.USER_INPUT_ERROR.value,
                                    error_source=ErrorSource.EMBEDDED_CODE.value,
                                    http_code_at_source=0)
                raise StepExecutionError(msg, error_obj)


    # Check if duration is provided, if so validate that start/end time are not both present, then compute new start/end time
    if duration:
        if end_time and start_time:
            msg = "Durations are not valid if both a start and end time are provided"
            # log statement
            logger.error(msg, extra = {
                "event": EventName.TIME_VALIDATION.value,
                "data": {
                    "message": msg,
                    "error_type": ErrorType.USER_INPUT_ERROR.value,
                    "error_source": ErrorSource.EMBEDDED_CODE.value,
                    "http_code_at_source": 0,
                    "details": []
                }
            })
            error_obj = create_step_error(message=msg,
                                details=[],
                                error_type=ErrorType.USER_INPUT_ERROR.value,
                                error_source=ErrorSource.EMBEDDED_CODE.value,
                                http_code_at_source=0)
            raise StepExecutionError(msg, error_obj)

        try:
            # handle either integer string or float string
            duration_sec = float(duration)
        except ValueError:
            msg = "Duration is not a number: " + duration
            # log statement
            logger.error(msg, extra = {
                "event": EventName.TIME_VALIDATION.value,
                "data": {
                    "message": msg,
                    "error_type": ErrorType.USER_INPUT_ERROR.value,
                    "error_source": ErrorSource.EMBEDDED_CODE.value,
                    "http_code_at_source": 0,
                    "details": []
                }
            })
            error_obj = create_step_error(message=msg,
                                details=[],
                                error_type=ErrorType.USER_INPUT_ERROR.value,
                                error_source=ErrorSource.EMBEDDED_CODE.value,
                                http_code_at_source=0)
            raise StepExecutionError(msg, error_obj)            

        if end_time:
            if time_type in ['SCET','ERT']:
                start_time=end_time-timedelta(seconds=duration_sec)
            else:
                start_time=end_time-duration_sec

        if start_time:
            if time_type in ['SCET','ERT']:
                #start_time = datetime.strptime(start_time, "%Y-%jT%H:%M:%S")
                end_time=start_time+timedelta(seconds=duration_sec)
            else:
                end_time=start_time+duration_sec

    # If timeout is provided, start time must be present and end time must not be present.
    if include_timeout and timeout:
        if not start_time:
            msg = "A start time must be provided to use timeout"
            # log statement
            logger.error(msg, extra = {
                "event": EventName.TIME_VALIDATION.value,
                "data": {
                    "message": msg,
                    "error_type": ErrorType.USER_INPUT_ERROR.value,
                    "error_source": ErrorSource.EMBEDDED_CODE.value,
                    "http_code_at_source": 0,
                    "details": []
                }
            })
            error_obj = create_step_error(message=msg,
                                details=[],
                                error_type=ErrorType.USER_INPUT_ERROR.value,
                                error_source=ErrorSource.EMBEDDED_CODE.value,
                                http_code_at_source=0)
            raise StepExecutionError(msg, error_obj)

        if end_time:
            msg = "timeout cannot be used when end time is specified"
            # log statement
            logger.error(msg, extra = {
                "event": EventName.TIME_VALIDATION.value,
                "data": {
                    "message": msg,
                    "error_type": ErrorType.USER_INPUT_ERROR.value,
                    "error_source": ErrorSource.EMBEDDED_CODE.value,
                    "http_code_at_source": 0,
                    "details": []
                }
            })
            error_obj = create_step_error(message=msg,
                                details=[],
                                error_type=ErrorType.USER_INPUT_ERROR.value,
                                error_source=ErrorSource.EMBEDDED_CODE.value,
                                http_code_at_source=0)
            raise StepExecutionError(msg, error_obj)
        
        if time_type in ['SCET','ERT']:
            end_time = start_time + timedelta(seconds=timeout)
        else:
            end_time = start_time + timeout

    # Check if lookback is provided, if so validate that start time is present, then compute new start time
    if lookback:
        if not start_time:
            msg = "A start time must be provided to use lookback"
            # log statement
            logger.error(msg, extra = {
                "event": EventName.TIME_VALIDATION.value,
                "data": {
                    "message": msg,
                    "error_type": ErrorType.USER_INPUT_ERROR.value,
                    "error_source": ErrorSource.EMBEDDED_CODE.value,
                    "http_code_at_source": 0,
                    "details": []
                }
            })
            error_obj = create_step_error(message=msg,
                                details=[],
                                error_type=ErrorType.USER_INPUT_ERROR.value,
                                error_source=ErrorSource.EMBEDDED_CODE.value,
                                http_code_at_source=0)
            raise StepExecutionError(msg, error_obj)
        else:
            if time_type in ['SCET','ERT']:
                start_time=start_time-timedelta(seconds=lookback)
            else:
                start_time=start_time-lookback

    # Convert the times back to strings (for use in queries)
    if start_time:
        if time_type in ['SCET','ERT']:
            start_time=start_time.strftime("%Y-%jT%H:%M:%S")
        else:
            start_time=str(start_time)

    if end_time:
        if time_type in ['SCET','ERT']:
            end_time=end_time.strftime("%Y-%jT%H:%M:%S")
        else:
            end_time=str(end_time)

    return translated_start_time, translated_end_time, start_time, end_time


@ing_profile('DEBUG')
def register_session(data_path, session):
    '''
    This function updates or adds to the internal mapping of ampcs_sesison_information

    :param data_path: The description of the session
    :param session:  The AMPCS session id
    :return: None
    '''

    if data_path is not None:
        data_path = data_path.strip()
        
    found=False
    for entry in ic.ampcs_session_information:
        if entry['data_path'] == data_path:
            msg = "Updating existing data_path: {} with session_id: {} (was {})".format(data_path,session,entry['session_id'])
            logger.info(msg, extra= {
                "event": EventName.REGISTER_DATA_PATH.value
            })   
            entry['session_id'] = session
            found=True

    if not found:
        msg = "Adding new mapping data_path: {} and session: {}.".format(data_path, session)
        logger.info(msg, extra= {
            "event": EventName.REGISTER_DATA_PATH.value
        })   
        new_entry={'data_path' : data_path,'session_id': session}
        ic.ampcs_session_information.append(new_entry)

    return

def decode_ingenium_token(verify=True):

    token = ic.ing_token
    ingenium_public_pem = os.environ.get("PUBLIC_PEM")
    decoded = jwt.decode(token,
                         ingenium_public_pem,
                         algorithms=["RS256"],
                         options={"verify_signature": verify})
    return decoded

def decode_venue_token(verify=True):

    token = ic.venue_token
    exec_public_pem = os.environ.get("EXEC_VENUE_PUBLIC_PEM")
    decoded = jwt.decode(token,
                         exec_public_pem,
                         algorithms=["RS256"],
                         options={"verify_signature": verify})
    return decoded

def refresh_venue_tokens():
    
    # decode ic.regular token and get data to become an execution token 
    try:
        # use verify False so that we can renew an expired token when
        # the previous step took a long time
        jwt_info = decode_venue_token(verify=False)
    except Exception as e:
        msg = "Ingenium venue token could not be decoded"
        #TODO: add logging
        error_obj = create_step_error(message=msg,
                            details=[str(e)],
                            error_type=ErrorType.INGENIUM_SERVICE_ERROR.value,
                            error_source=ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)
        raise StepExecutionError(msg, error_obj)        
    
    exec_private_pem = os.environ.get("EXEC_VENUE_PRIVATE_PEM")
    
    iat = int(time.time())
    jwt_info.update({"iat": iat})
    exp = iat + (30*60)
    jwt_info.update({"exp": exp})

    new_venue_token = jwt.encode(jwt_info,
                           exec_private_pem,
                           algorithm="RS256")
    # PyJWT >= 2 returns a str; older versions returned bytes. Normalize to str.
    ic.venue_token = new_venue_token.decode('utf-8') if isinstance(new_venue_token, bytes) else new_venue_token

    # update cache in redis
    exec_hash = HASH_TEMPLATE.format(ic.execution_id)
    redis_client.hset(exec_hash, mapping={'venue_token': ic.venue_token})


def refresh_ingenium_token():

    # decode ic.regular token and get data to become an execution token 
    try:
        # use verify False so that we can renew an expired token when
        # the previous actions took a long time
        jwt_info = decode_ingenium_token(verify=False)
    except Exception as e:
        msg = "Ingenium token could not be decoded"
        # TODO: add logging
        error_obj = create_step_error(message=msg,
                            details=[str(e)],
                            error_type=ErrorType.INGENIUM_SERVICE_ERROR.value,
                            error_source=ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)
        raise StepExecutionError(msg, error_obj)        
    
    ing_private_pem = os.environ.get("PRIVATE_PEM")
    
    iat = int(time.time())
    jwt_info.update({"iat": iat})
    exp = iat + (30*60)
    jwt_info.update({"exp": exp})

    new_ing_token = jwt.encode(jwt_info,
                           ing_private_pem,
                           algorithm="RS256")
    # PyJWT >= 2 returns a str; older versions returned bytes. Normalize to str.
    ic.ing_token = new_ing_token.decode('utf-8') if isinstance(new_ing_token, bytes) else new_ing_token

    # update cache in redis
    exec_hash = HASH_TEMPLATE.format(ic.execution_id)
    redis_client.hset(exec_hash, mapping={'ing_token': ic.ing_token})

def get_authorization_header():
    # make a deep copy not to change the base headers
    header = copy.deepcopy(ic.header)
    header["Authorization"] = "Bearer {}".format(ic.venue_token)
    return header

def get_cs_files_authorization_header():

    header = {}
    header["Authorization"] = "Bearer {}".format(ic.venue_token)
    header["Accept"] = "application/x-tar"
    return header

def get_ing_authorization_header():
    # make a deep copy not to change the base headers
    header = copy.deepcopy(ic.header)
    header["Authorization"] = "Bearer {}".format(ic.ing_token)
    return header    

def get_timeout_with_margin5(timeout):
    # 5 secs margin
    return timeout + 5 

@ing_profile('INFO')
def get_venue_config():
    '''
    This function queries the venue configuration service for the current venues configuration
    :return: List of Dictionaries in JSON

    Sample format: [{"name": "StarCamera", "type": "EM", "status": "INSTALLED", "serial": "SN 20323232"},
                    {"name": "INSTRUMENT1", "type": "SIM", "status": "INSTALLED", "serial": "V3.2"},
                    {"name": "FSW_IMAGE_1", "type": "FLIGHT", "status": "INSTALLED", "serial": "3.0.1"}]
    '''

    # Build the header and path request
    header = get_ing_authorization_header()
    venue_config_api_url = get_venue_configurations_url()
    path = "{}/{}/elements".format(venue_config_api_url, ic.venue_id)
    msg = "Making REST call for venue configuration: {}".format(path)

    # Make the REST call to venue configuration
    try:
        response=requests.get(path,headers=header,verify=ic.ssl_verify,timeout=ic.rest_timeout)
        determine_response(endpoint_name="GetConfig", query_response=response)

        if response.status_code != 200:
            msg = "REST call for GetVenueConfig was unsuccessful. path: {} status_code: {}".format(path, response.status_code)
            
            # log statement
            logger.error(msg, extra = {
                "event": EventName.QUERY_VENUE_CONFIGURATION.value,
                "data": {
                    "message": msg,
                    "error_type": ErrorType.QUERY_ERROR.value,
                    "error_source": ErrorSource.VENUE_CONFIGURATION.value,
                    "http_code_at_source": 400
                }
            })

            error_obj = create_step_error(message='Call to venue_config failed: {}'.format(path),
                                details=[response.text],
                                error_type=ErrorType.QUERY_ERROR.value,
                                error_source='VENUE_CONFIGURATION',
                                http_code_at_source=response.status_code)
            raise StepExecutionError(msg, error_obj)

        config = json.loads(response.text)

    except StepExecutionError:

        raise

    except Exception as ex:
            msg = "GetConfig - REST call for venue configuration ({}) unsuccessful - {}".format(path, traceback.format_exc())
            
            # log statement
            logger.error(msg, extra = {
                "event": EventName.QUERY_VENUE_CONFIGURATION.value,
                "data": {
                    "message": msg,
                    "error_type": ErrorType.QUERY_ERROR.value,
                    "error_source": ErrorSource.VENUE_CONFIGURATION.value,
                    "http_code_at_source": 400
                }
            })

            error_obj = create_step_error(message='Call to venue configuration failed: {}'.format(path),
                                          details=[traceback.format_exc()],
                                          error_type=ErrorType.QUERY_ERROR.value,
                                          error_source='VENUE_CONFIGURATION',
                                          http_code_at_source=0)
            raise StepExecutionError(str(ex), error_obj)

    list_of_config_elements=[]

    if type(config) == list:
    # Parse the resulting data into the return format
        for config_element in config:
            element={"config_elem_name":config_element['elem_name'],"type":config_element['type'],"status":config_element['status'], \
                     "serial":config_element['serial_number'],"elem_id":config_element['elem_id']}
            list_of_config_elements.append(element)
    else:
        raise Exception('Venue configuration is not in the expected format: ' + str(config))

    return list_of_config_elements

@ing_profile('INFO')
def update_venue_config(element):
    """
    This function takes a defined set of venue configuration information, confirms the element is present on the current
    venue, combines it with venue specific information,and then updated the venue configuration of the venue
    via the VCS API.

    :param element: Venue Configuration element definition (dictionary)
    Sample format:
        {"name": "StarCamera", "type": "EM", "status": "INSTALLED", "serial": "SN 20323232",
        "notes" : "Digital Electronics only"}
    :return: Updated Venue Configuration parameters including a "last_updated" timestamp.
    Same format:
        {'type':'FLIGHT', 'status':'INSTALLED', 'serial_number':'SN 20323232', 'notes':'Installed to support test X',
         'description':'this is an update', 'venue_id':'10', 'venue_name':'venue_1', 'elem_id':'id-301', 'elem_name':'StarCamera',
         'last_updated':'2017-10-16T15:19:51.000Z'}
    """

    # First we need to query the venue and determine the element id of the element to update.
    current_config = get_venue_config()

    # Walk through the config and find the elem_id (or raise a fault if not found)
    element_found = False
    element_id = None
    for item in current_config:
        if element['config_elem_name'] == item['config_elem_name']:
            element_id = item['elem_id']
            element_found = True

    # If the element name is not found in the list raise a fault
    # (can't add configurable elements to a venue via the step)
    if not element_found:
        msg = "Unable to find element with name: {} on venue: {} (venue_id: {})".format(element['config_elem_name'],ic.venue_name,ic.venue_id)
        # log statement
        logger.error(msg, extra = {
            "event": EventName.QUERY_VENUE_CONFIGURATION.value,
            "data": {
                "message": msg,
                "error_type": ErrorType.ELEMENT_NOT_FOUND.value,
                "error_source": ErrorSource.VENUE_CONFIGURATION.value,
                "http_code_at_source": 400
            }
        })
        error_obj = create_step_error(message=msg,
                                      details=[],
                                      error_type=ErrorType.ELEMENT_NOT_FOUND.value,
                                      error_source='VENUE_CONFIGURATION',
                                      http_code_at_source=0)
        raise StepExecutionError(msg, error_obj)

    header= get_ing_authorization_header()
    venue_config_api_url = get_venue_configurations_url()
    path = "{}/{}/elements/{}".format(venue_config_api_url, ic.venue_id, element_id)

    body_data={}
    if element["type"] != None:
        body_data['type']=element["type"]
    if element["status"] != None:
        body_data['status'] = element["status"]
    if element["serial"] != None:
        body_data['serial_number'] = element["serial"]
    if element['notes'] != None:
        body_data['notes'] = element["notes"]
    if ic.venue_id != None:
        body_data["venue_id"] = ic.venue_id
    if ic.venue_name != None:
        body_data["venue_name"] = ic.venue_name
    if element["config_elem_name"] != None:
        body_data["elem_name"] = element["config_elem_name"]

    body_data["elem_id"] = element_id
    # Make the REST call to venue configuration
    try:
        config = requests.patch(path, headers=header, verify=ic.ssl_verify, data=json.dumps(body_data), timeout=ic.rest_timeout)
        determine_response(endpoint_name="UpdateConfig", query_response=config, body_data=body_data)
    except:
        msg= "UpdateConfig - REST call for venue configuration ({}) unsuccessful".format(path)
        
        # log statement
        logger.error(msg, extra = {
            "event": EventName.QUERY_VENUE_CONFIGURATION.value,
            "data": {
                "message": msg,
                "error_type": ErrorType.QUERY_ERROR.value,
                "error_source": ErrorSource.VENUE_CONFIGURATION.value,
                "http_code_at_source": 400,
                "details": [traceback.format_exc()]
            }
        })

        error_obj = create_step_error(message='Call to venue_service failed: {}'.format(path),
                                      details=[traceback.format_exc()],
                                      error_type=ErrorType.QUERY_ERROR.value,
                                      error_source=ErrorSource.VENUE_CONFIGURATION.value,
                                      http_code_at_source=config.status_code)
        raise StepExecutionError(msg, error_obj)

    configs_list = json.loads(config.text)

    return configs_list


@ing_profile('INFO')
def ChillEVRQuery(data_path,time_type,evr_name=None,evr_id=None,evr_type=None,evr_level=None, evr_module=None, start_time=None, \
                  end_time=None,timeout=ic.evr_chill_timeout, \
                  message_filter=None):
    '''

    This function performs a REST query to the venue to retrieve a filtered set of EVRS. The majority of the filtering
    is performed via the chill query on the venue with the message filter being applied here.

    Note that all but the data_path variable is considered optional (but without filtering this query can return a lot
    EVRs.

    :param evr_name: The name (or partial string) to filter on
    :param evr_id: The Id number of the EVR (int)
    :param evr_type: The type of the EVR (SSE, RT, REC) - if nothing is provided Chill defaults to RT AND REC
    :param evr_level: The level of EVR (varies per project)
    :param start_time: The start time of the query
    :param end_time: The end time of the query
    :param time_type: SCLK/SCET/ERT
    :param data_path: [Required] The data_path (which translates into the session) to query against
    :param message_filter: A basic inclusive text filter
    :param evr_module: Module of EVRs to retreive
    :return: A list of dictionaries in JSON

    Sample:

    [                  {
                            "evr_name": "SSE_EVR_POWER_ON",
                            "session_id": 3232,
                            "vcid": 0,
                            "event_id": 3487928332,
                            "evr_level": "INFO",
                            "fromSSE": true,
                            "evrMessage": "SRU_SIM has been powered on",
                            "evrModule": "SSE",
                            "sclk": "527925356"
                            "ert": "2017-032T00:23:03",
                            "scet": "2017-032T00:23:01",
                            "isRecorded": true
                        },
                        {
                            "evr_name": "SSE_EVR_POWER_OFF",
                            "session_id": 3232,
                            "vcid": 0,
                            "event_id": 3487928333,
                            "evr_level": "INFO",
                            "fromSSE": true,
                            "evrMessage": "SRU_SIM has been powered off",
                            "evrModule": "SSE",
                            "sclk": "527925376"
                            "ert": "2017-032T00:23:22",
                            "scet": "2017-032T00:23:21",
                            "isRecorded": true
                        }
                    ]
    '''

    # Build the header and path request
    header = get_authorization_header()
    path = get_evr_chill_url()

    # Get the correct session via the data path

    # If you are testing this call locally, uncomment the function below to manually register a session to your data path
    #register_session(data_path, 3)
    try:
        session = get_session_information(data_path)
    except Exception as ex:
        msg = 'Failed to get session info for data_path: {}'.format(data_path)
        
        # log statement
        logger.error(msg, extra = {
            "event": EventName.DATA_PATH_CHECK.value,
            "data": {
                "message": msg,
                "error_type": ErrorType.USER_INPUT_ERROR.value,
                "error_source": ErrorSource.EMBEDDED_CODE.value,
                "http_code_at_source": 0,
                "details": [str(ex)]
            }
        })
        error_obj = create_step_error(message=msg,
                            details=[traceback.format_exc()],
                            error_type=ErrorType.USER_INPUT_ERROR.value,
                            error_source=ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)
        raise StepExecutionError(str(ex), error_obj)

    # Build the REST body parameter (only add elements that are not equal to None)
    body_data={'sessionId': session}

    if evr_type:
        body_data["evrType"]= [evr_type]
    if evr_name:
        body_data["evrName"]= evr_name
    if evr_id:
        try:
            body_data["eventId"]= int(evr_id)
        except:
            msg = "Field 'EVR ID' is a non-integer value: {}. Please use an integer value.".format(evr_id)
            error_obj = create_step_error(message=msg,
                                details=[],
                                error_type=ErrorType.USER_INPUT_ERROR.value,
                                error_source=ErrorSource.EMBEDDED_CODE.value,
                                http_code_at_source=0)
            raise StepExecutionError(msg, error_obj)            
    if evr_level:
        body_data["evrLevel"] = evr_level
    if time_type:
        body_data["timeType"] = time_type
    if start_time:
        body_data['startTime']= start_time
    if end_time:
        body_data['endTime']= end_time

    body_data["timeout"] = timeout
    requests_timeout = get_timeout_with_margin5(timeout)

    try:
        res = requests.get(path,json=body_data,headers=header,verify=ic.ssl_verify,timeout=requests_timeout)
        if res.status_code != 200:

            msg = "REST call for ChillEVR was unsuccessful. path: {} status_code: {}".format(path, res.status_code)
            
            # The error response may not be a JSON string. Handle either case.
            err_dict = res.json()
            if isinstance(err_dict, dict):
                detail = err_dict['message']
            else:
                detail = res.text
            
            error_obj = create_step_error(message='Call to venue_service failed: {}'.format(path),
                                details=[detail],
                                error_type=ErrorType.INGENIUM_SERVICE_ERROR.value,
                                error_source=ErrorSource.VENUE_SERVICE.value,
                                http_code_at_source=res.status_code)
            raise StepExecutionError(msg, error_obj)


        determine_response("ChillEVR", res, body_data)
        evrs = json.loads(res.text)
    except StepExecutionError:
        # simply re-throw it
        raise
    except Exception as ex:
        msg = "REST call for ChillEVR ({}) unsuccessful - {}".format(path, traceback.format_exc())

        error_obj = create_step_error(message='Call to venue_service failed: {}'.format(path),
                            details=[traceback.format_exc()],
                            error_type=ErrorType.INGENIUM_SERVICE_ERROR.value,
                            error_source=ErrorSource.VENUE_SERVICE.value,
                            http_code_at_source=0)
        raise StepExecutionError(str(ex), error_obj)

    # If there is a message filter iterate on the results to apply it
    filtered_list=[]

    for evr in evrs:
        # If no filter - just append the results
        if message_filter == None:
            filtered_list.append(evr)
        # Otherwise append the result if the message filter is in the message
        # TODO The filter is basic - we could make a regex filter if desired
        # TODO - unclear if that would confuse end users.
        elif message_filter in evr["evrMessage"]:
                filtered_list.append(evr)

    # return the results
    return filtered_list

@ing_profile('INFO')
def ChillEHAQuery(data_path,time_type,channel_id=None,channel_type=None,start_time=None, \
                  end_time=None,timeout=ic.eha_chill_timeout):
    '''

    This function performs a REST query to the venue to retrieve a filtered set of EVRS. The majority of the filtering
    is performed via the chill query on the venue with the message filter being applied here.

    Note that all but the data_path variable is considered optional (but without filtering this query can return a lot
    EVRs.

    :param channel_id: List of channels to query
    :param channel_type: The type of the channels (SSE, RT, REC) - if nothing is provided Chill defaults to RT AND REC
    :param start_time: The start time of the query
    :param end_time: The end time of the query
    :param time_type: SCLK/SCET/ERT
    :param data_path: [Required] The data_path (which translates into the session) to query against
    :param timeout: timeout on the channel query
    :return: A list of dictionaries in JSON

    '''

    # Build the header and path request
    header = get_authorization_header()
    path = get_eha_chill_url()

    # Get the correct session via the data path
    # register_session("SIDE A", 6)
    try:
        session = get_session_information(data_path)
    except Exception as ex:
        msg = 'Failed to get session info for data_path: {}'.format(data_path)
        
        # log statement
        logger.error(msg, extra = {
            "event": EventName.DATA_PATH_CHECK.value,
            "data": {
                "message": msg,
                "error_type": ErrorType.USER_INPUT_ERROR.value,
                "error_source": ErrorSource.EMBEDDED_CODE.value,
                "http_code_at_source": 0,
                "details": [str(ex)]
            }
        })

        error_obj = create_step_error(message=msg,
                            details=[traceback.format_exc()],
                            error_type=ErrorType.USER_INPUT_ERROR.value,
                            error_source=ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)
        raise StepExecutionError(str(ex), error_obj)

    # Build the REST body parameter (only add elements that are not equal to None)
    body_data= {'sessionId': session}

    # populate body data json
    if channel_id != None:
        if channel_id == "":
            body_data["channelIds"] = []
        else:
            # Channel id field in core spec is a string type
            body_data['channelIds']= [channel_id]
    if channel_type != None:
        body_data['channelTypes']= [channel_type]
    if start_time != None:
        body_data['startTime']=start_time
    if end_time != None:
        body_data['endTime']=end_time
    if time_type != None:
        body_data['timeType']=time_type

    body_data["timeout"] = timeout
    requests_timeout = get_timeout_with_margin5(timeout)

    try:
        channels=requests.get(path,json=body_data,headers=header,verify=ic.ssl_verify,timeout=requests_timeout)

        if channels.status_code != 200:

            msg = "REST call for ChillEHA was unsuccessful. path: {} status_code: {}".format(path, channels.status_code)

            error_obj = create_step_error(message='Call to venue_service failed: {}'.format(path),
                                details=[channels.json().get("message")],
                                error_type=ErrorType.INGENIUM_SERVICE_ERROR.value,
                                error_source=ErrorSource.VENUE_SERVICE.value,
                                http_code_at_source=channels.status_code)
            raise StepExecutionError(msg, error_obj)

        determine_response(endpoint_name="ChillEHA", query_response=channels, body_data=body_data)
        channels = json.loads(channels.text)

    except StepExecutionError:
        # simply re-throw it
        raise
    except Exception as ex:
        msg = "REST call for ChillEHA ({}) unsuccessful - {}".format(path, traceback.format_exc())

        error_obj = create_step_error(message='Call to venue_service failed: {}'.format(path),
                            details=[traceback.format_exc()],
                            error_type=ErrorType.INGENIUM_SERVICE_ERROR.value,
                            error_source=ErrorSource.VENUE_SERVICE.value,
                            http_code_at_source=0)
        raise StepExecutionError(str(ex), error_obj)

    # return the results
    return channels


def CommandFSW(data_path, command_string, string_selection, validate=True, timeout=ic.cmd_timeout):
    '''
    This function builds and sends a FSW command.

    :param data_path: [Required] The data_path (which translates into the session) to query against
    :param command_string: [Required] The command string including the command stem and any arguments for the command.
    :param validate: If validate=True, AMPCS validates the command against the FSW dict before radiating.
    :param timeout: The timeout on the dispatch process (in seconds)
    :returns: An object mirroring the request given and the dispatch time.

    '''

    # get authorization information
    header = get_authorization_header()

    # get path for cmd api call
    cmd_url = get_cmd_url()
    path = "{}/fsw_cmd".format(cmd_url)

    # get session information from data path
    try:
        session = get_session_information(data_path)
    except Exception as ex:
        msg = 'Failed to get session info for data_path: {}'.format(data_path)
        
        # log statement
        logger.error(msg, extra = {
            "event": EventName.DATA_PATH_CHECK.value,
            "data": {
                "message": msg,
                "error_type": ErrorType.USER_INPUT_ERROR.value,
                "error_source": ErrorSource.EMBEDDED_CODE.value,
                "http_code_at_source": 0,
                "details": [str(ex)]
            }
        })

        error_obj = create_step_error(message=msg,
                            details=[traceback.format_exc()],
                            error_type=ErrorType.USER_INPUT_ERROR.value,
                            error_source=ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)
        raise StepExecutionError(str(ex), error_obj)

    body_data={'sessionId': session}

    # populate body data json
    if command_string:
        body_data["commandString"] = command_string
    if string_selection:
        body_data["stringSelection"] = string_selection
    if validate:
        body_data["validate"] = validate

    body_data["timeout"] = timeout
    requests_timeout = get_timeout_with_margin5(timeout)

    try:
        fsw_dispatch = requests.post(path, json=body_data, headers=header, verify=ic.ssl_verify,timeout=requests_timeout)
        if fsw_dispatch.status_code != 200:
            msg = "REST call for CommandFSW was unsuccessful. path: {} status_code: {}".format(path, fsw_dispatch.status_code)

            # step level needs to extract "message" for error message
            error_obj = create_step_error(message='Call to venue_service failed: {}'.format(path),
                                details=[fsw_dispatch.json().get("message")],
                                error_type=ErrorType.DISPATCH_ERROR.value,
                                error_source=ErrorSource.VENUE_SERVICE.value,
                                http_code_at_source=fsw_dispatch.status_code)
            raise StepExecutionError(msg, error_obj)

        determine_response(endpoint_name="CommandFSW", query_response=fsw_dispatch, body_data=body_data)
        return json.loads(fsw_dispatch.text)

    except StepExecutionError:
        # simply re-throw it
        raise
    except Exception as ex:
        msg = "REST call for CommandFSW ({}) unsuccessful - {}".format(path, traceback.format_exc())

        error_obj = create_step_error(message='Call to venue_service failed: {}'.format(path),
                            details=[traceback.format_exc()],
                            error_type=ErrorType.DISPATCH_ERROR.value,
                            error_source=ErrorSource.VENUE_SERVICE.value,
                            http_code_at_source=0)
        raise StepExecutionError(str(ex), error_obj)



def CommandHW(data_path, command_stem, string_selection, timeout=ic.cmd_timeout):
    '''
    This function builds and sends a HW command.

    :param data_path: [Required] The data_path (which translates into the session) to query against
    :param command_stem: [Required] The command stem of the HW Command to build/send
    :param timeout: The timeout on the dispatch process (in seconds)
    :returns: An object mirroring the request given and the dispatch time.

    '''

    # get authorization information
    header = get_authorization_header()

    # get path for cmd api call
    cmd_url = get_cmd_url()
    path = "{}/hw_cmd".format(cmd_url)

    # get session information from data path
    try:
        session = get_session_information(data_path)
    except Exception as ex:
        msg = 'Failed to get session info for data_path: {}'.format(data_path)
        
        # log statement
        logger.error(msg, extra = {
            "event": EventName.DATA_PATH_CHECK.value,
            "data": {
                "message": msg,
                "error_type": ErrorType.USER_INPUT_ERROR.value,
                "error_source": ErrorSource.EMBEDDED_CODE.value,
                "http_code_at_source": 0,
                "details": [str(ex)]
            }
        })

        error_obj = create_step_error(message=msg,
                            details=[traceback.format_exc()],
                            error_type=ErrorType.USER_INPUT_ERROR.value,
                            error_source=ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)
        raise StepExecutionError(str(ex), error_obj)

    body_data={'sessionId': session}

    # populate body data json
    if command_stem:
        body_data["commandStem"] = command_stem
    if string_selection:
        body_data["stringSelection"] = string_selection
    
    body_data["timeout"] = timeout
    requests_timeout = get_timeout_with_margin5(timeout)

    try:
        hw_dispatch = requests.post(path, json=body_data, headers=header, verify=ic.ssl_verify,timeout=requests_timeout)

        if hw_dispatch.status_code != 200:

            msg = "REST call for CommandHW was unsuccessful. path: {} status_code: {}".format(path, hw_dispatch.status_code)

            error_obj = create_step_error(message=msg,
                                details=[hw_dispatch.json().get("message")],
                                error_type=ErrorType.DISPATCH_ERROR.value,
                                error_source=ErrorSource.VENUE_SERVICE.value,
                                http_code_at_source=hw_dispatch.status_code)
            raise StepExecutionError(msg, error_obj)

        determine_response(endpoint_name="CommandHW", query_response=hw_dispatch, body_data=body_data)
        return json.loads(hw_dispatch.text)

    except StepExecutionError:
        # simply re-throw it
        raise
    except Exception as ex:
        msg = "REST call for CommandHW ({}) unsuccessful - {}".format(path, traceback.format_exc())

        error_obj = create_step_error(message='Call to venue_service failed: {}'.format(path),
                            details=[traceback.format_exc()],
                            error_type=ErrorType.DISPATCH_ERROR.value,
                            error_source=ErrorSource.VENUE_SERVICE.value,
                            http_code_at_source=0)
        raise StepExecutionError(str(ex), error_obj)



def CommandSCMF(data_path, file_path, disable_checks=False, timeout=ic.cmd_timeout):
    '''
    This function sends an existing SCMF file to the vehicle.

    :param data_path: [Required] The data_path (which translates into the session) to query against
    :param file_path: [Required] The full path on the venue's file system to locate the file. (i.e. /proj/m20/test_23/supportfiles/file.scmf)
    :param disable_checks: Disables the check done by AMPCS for off-nominal test cases (i.e. verifying that the s/c returns error when bad commands scmf is passed in)
    :param timeout: The timeout on the dispatch process (in seconds)
    :returns: An object mirroring the request given and the dispatch time.

    '''

    # get authorization information
    header = get_authorization_header()

    # get path for cmd api call
    cmd_url = get_cmd_url()
    path = "{}/scmf".format(cmd_url)

    # get session information from data path
    try:
        session = get_session_information(data_path)
    except Exception as ex:
        msg = 'Failed to get session info for data_path: {}'.format(data_path)
        
        # log statement
        logger.error(msg, extra = {
            "event": EventName.DATA_PATH_CHECK.value,
            "data": {
                "message": msg,
                "error_type": ErrorType.USER_INPUT_ERROR.value,
                "error_source": ErrorSource.EMBEDDED_CODE.value,
                "http_code_at_source": 0,
                "details": [str(ex)]
            }
        })

        error_obj = create_step_error(message=msg,
                            details=[traceback.format_exc()],
                            error_type=ErrorType.USER_INPUT_ERROR.value,
                            error_source=ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)
        raise StepExecutionError(str(ex), error_obj)

    body_data = {'sessionId': session}

    # populate body data json
    if file_path:
        body_data["filePath"] = file_path

    body_data["disableChecks"] = True

    body_data["timeout"] = timeout
    requests_timeout = get_timeout_with_margin5(timeout)

    try:
        scmf_dispatch = requests.post(path, json=body_data, headers=header, verify=ic.ssl_verify, timeout=requests_timeout)

        if scmf_dispatch.status_code != 200:

            msg = "REST call for CommandSCMF was unsuccessful. path: {} status_code: {}".format(path, scmf_dispatch.status_code)
            error_obj = create_step_error(message='Call to venue_service failed: {}'.format(path),
                                details=[scmf_dispatch.json().get("message")],
                                error_type=ErrorType.DISPATCH_ERROR.value,
                                error_source=ErrorSource.VENUE_SERVICE.value,
                                http_code_at_source=scmf_dispatch.status_code)
            raise StepExecutionError(msg, error_obj)

        determine_response(endpoint_name="CommandSCMF", query_response=scmf_dispatch, body_data=body_data)
        return json.loads(scmf_dispatch.text)

    except StepExecutionError:
        # simply re-throw it
        raise
    except Exception as ex:
        msg = "REST call for CommandSCMF ({}) unsuccessful - {}".format(path, traceback.format_exc())

        error_obj = create_step_error(message='Call to venue_service failed: {}'.format(path),
                            details=[traceback.format_exc()],
                            error_type=ErrorType.DISPATCH_ERROR.value,
                            error_source=ErrorSource.VENUE_SERVICE.value,
                            http_code_at_source=0)
        raise StepExecutionError(str(ex), error_obj)

def CommandBinaryFile(data_path, source_file_path, target_file_path, file_type, overwrite, string_selection, timeout=ic.cmd_timeout):
    '''
    This function builds and sends a binary file

    :param data_path: [Required] The data_path (which translates into the session) to query against
    :param file_path: [Required] The full path on the venue's file system to locate the file. (i.e. /proj/m20/test_23/supportfiles/file.dat)
    :param file_location: [Requred] The full path on the vehicle's file system to send the file. (i.e. /eng/config/file.dat)
    :param file_type: [Required] The file type that should be used to build the binary file into a SCMF.
    :param overwrite: [Required] True if the file should overwrite the existing file in vehicle's file system
    :param timeout: The timeout on the dispatch process (in seconds)
    :returns: An object mirroring the request given and the dispatch time

    '''

    # get authorization information
    header = get_authorization_header()

    # get path for cmd api call
    cmd_url = get_cmd_url()
    path = "{}/binary_file".format(cmd_url)

    # get session information from data path
    try:
        session = get_session_information(data_path)
    except Exception as ex:
        msg = 'Failed to get session info for data_path: {}'.format(data_path)
        
        # log statement
        logger.error(msg, extra = {
            "event": EventName.DATA_PATH_CHECK.value,
            "data": {
                "message": msg,
                "error_type": ErrorType.USER_INPUT_ERROR.value,
                "error_source": ErrorSource.EMBEDDED_CODE.value,
                "http_code_at_source": 0,
                "details": [str(ex)]
            }
        })

        error_obj = create_step_error(message=msg,
                            details=[traceback.format_exc()],
                            error_type=ErrorType.USER_INPUT_ERROR.value,
                            error_source=ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)
        raise StepExecutionError(str(ex), error_obj)

    body_data = {'sessionId': session}

    # populate body data json
    if source_file_path:
        body_data["sourceFilePath"] = source_file_path
    if target_file_path:
        body_data["targetFilePath"] = target_file_path
    if file_type != None:
        # HK: venue server API specs expect an int, although I suspect string is used inside venueserver and MTAK.
        body_data["fileType"] = int(file_type)
    if overwrite != None:
        body_data["overwrite"] = overwrite
    if string_selection:
        body_data["stringSelection"] = string_selection
    
    body_data["timeout"] = timeout
    requests_timeout = get_timeout_with_margin5(timeout)

    try:
        binary_file_dispatch = requests.post(path, json=body_data, headers=header, verify=ic.ssl_verify, timeout=requests_timeout)

        if binary_file_dispatch.status_code != 200:
            msg = "REST call for CommandBinaryFile was unsuccessful. path: {} status_code: {}".format(path, binary_file_dispatch.status_code)

            error_obj = create_step_error(message='Call to venue_service failed: {}'.format(path),
                                details=[binary_file_dispatch.json().get("message")],
                                error_type=ErrorType.DISPATCH_ERROR.value,
                                error_source=ErrorSource.VENUE_SERVICE.value,
                                http_code_at_source=binary_file_dispatch.status_code)
            raise StepExecutionError(msg, error_obj)

        determine_response(endpoint_name="CommandBinaryFile", query_response=binary_file_dispatch, body_data=body_data)
        return json.loads(binary_file_dispatch.text)
    except StepExecutionError as ex:
        # simply re-throw it
        raise
    except Exception as ex:
        msg = "REST call for CommandBinaryFile ({}) unsuccessful - {}".format(path, traceback.format_exc())

        error_obj = create_step_error(message='Call to venue_service failed: {}'.format(path),
                            details=[traceback.format_exc()],
                            error_type=ErrorType.DISPATCH_ERROR.value,
                            error_source=ErrorSource.VENUE_SERVICE.value,
                            http_code_at_source=0)
        raise StepExecutionError(str(ex), error_obj)

def CommandSSE(data_path, command_string, timeout=ic.cmd_timeout):
    '''
    This function sends simulation and support equipment command.

    :param data_path: [Required] The data_path (which translates into the session) to query against
    :param command_string: [Required] The command string including the command stem and any arguments for the command.
    :param timeout: The timeout on the dispatch process (in secconds)
    :returns: An object mirroring the request given and the dispatch time

    '''
    # get authorization information
    header = get_authorization_header()

    # get path for cmd api call
    cmd_url = get_cmd_url()
    path = "{}/sse".format(cmd_url)

    # get session information from data path
    try:
        session = get_session_information(data_path)
    except Exception as ex:
        msg = 'Failed to get session info for data_path: {}'.format(data_path)
        
        # log statement
        logger.error(msg, extra = {
            "event": EventName.DATA_PATH_CHECK.value,
            "data": {
                "message": msg,
                "error_type": ErrorType.USER_INPUT_ERROR.value,
                "error_source": ErrorSource.EMBEDDED_CODE.value,
                "http_code_at_source": 0,
                "details": [str(ex)]
            }
        })

        error_obj = create_step_error(message=msg,
                            details=[traceback.format_exc()],
                            error_type=ErrorType.USER_INPUT_ERROR.value,
                            error_source=ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)
        raise StepExecutionError(str(ex), error_obj)

    body_data = {'sessionId': session}

    # populate body data json
    if command_string:
        body_data["commandString"] = command_string
    
    body_data["timeout"] = timeout
    requests_timeout = get_timeout_with_margin5(timeout)

    try:
        sse_dispatch = requests.post(path, json=body_data, headers=header, verify=ic.ssl_verify, timeout=requests_timeout)
        if sse_dispatch.status_code != 200:

            msg = "REST call for CommandSSE was unsuccessful. path: {} status_code: {}".format(path, sse_dispatch.status_code)
            error_obj = create_step_error(message='Call to venue_service failed: {}'.format(path),
                                details=[sse_dispatch.json().get("message")],
                                error_type=ErrorType.DISPATCH_ERROR.value,
                                error_source=ErrorSource.VENUE_SERVICE.value,
                                http_code_at_source=sse_dispatch.status_code)
            raise StepExecutionError(msg, error_obj)

        determine_response(endpoint_name="CommandSSE", query_response=sse_dispatch, body_data=body_data)
        return json.loads(sse_dispatch.text)
    except StepExecutionError:
        # simply re-throw it
        raise
    except Exception as ex:
        msg = "REST call for CommandSSE ({}) unsuccessful - {}".format(path, traceback.format_exc())

        error_obj = create_step_error(message='Call to venue_service failed: {}'.format(path),
                            details=[traceback.format_exc()],
                            error_type=ErrorType.DISPATCH_ERROR.value,
                            error_source=ErrorSource.VENUE_SERVICE.value,
                            http_code_at_source=0)
        raise StepExecutionError(str(ex), error_obj)

def StartMTAK(session, default_cmd_string, timeout=ic.mtak_timeout):
    '''
    This function starts MTAK on the venue GDS machine per the specified configuration.

    :param session: [Required] The session correlated to your data path
    :param timeout: The timeout on the dispatch process (in secconds)
    :returns: An object containing the session ID and the start time

    '''
    # get authorization information
    header = get_authorization_header()

    # get path for cmd api call
    mtak_url = get_mtak_url()
    path = "{}/start".format(mtak_url)

    if type(session) != list:
        msg="Session ID(s) must be in array format."
        
        # log statement
        logger.error(msg, extra = {
            "event": EventName.DATA_PATH_CHECK.value,
            "data": {
                "message": msg,
                "error_type": ErrorType.USER_INPUT_ERROR.value,
                "error_source": ErrorSource.EMBEDDED_CODE.value,
                "http_code_at_source": 0
            }
        })

        error_obj = create_step_error(message=msg,
                            details=[traceback.format_exc()],
                            error_type=ErrorType.USER_INPUT_ERROR.value,
                            error_source=ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)
        raise StepExecutionError(msg, error_obj)


    body_data = {'sessionIds': session}

    # populate body data json
    if default_cmd_string:
        body_data["defaultCmdString"] = default_cmd_string

    body_data["timeout"] = timeout
    requests_timeout = get_timeout_with_margin5(timeout)

    try:
        mtak_start = requests.post(path, json=body_data, headers=header, verify=ic.ssl_verify, timeout=requests_timeout)

        if mtak_start.status_code != 200:

            msg = "REST call for StartMTAK was unsuccessful. path: {} status_code: {}".format(path, mtak_start.status_code)

            error_obj = create_step_error(message='Call to venue_service failed: {}'.format(path),
                                details=[mtak_start.json().get("message")],
                                error_type=ErrorType.QUERY_ERROR.value,
                                error_source=ErrorSource.VENUE_SERVICE.value,
                                http_code_at_source=mtak_start.status_code)
            raise StepExecutionError(msg, error_obj)

        determine_response(endpoint_name="StartMTAK", query_response=mtak_start, body_data=body_data)
        return json.loads(mtak_start.text)

    except StepExecutionError:
        # simply re-throw it
        raise
    except Exception as ex:
        msg = "REST call for StartMTAK ({}) unsuccessful - {}".format(path, traceback.format_exc())

        error_obj = create_step_error(message='Call to venue_service failed: {}'.format(path),
                            details=[traceback.format_exc()],
                            error_type=ErrorType.QUERY_ERROR.value,
                            error_source=ErrorSource.VENUE_SERVICE.value,
                            http_code_at_source=0)
        raise StepExecutionError(str(ex), error_obj)


def ShutdownMTAK():
    '''
    This function shuts down all running mtak on the venue

    no parameters needed to query API endpoint

    '''

    # get authorization information
    get_header = get_authorization_header()
    header = {"Authorization": get_header["Authorization"]}

    # get path for cmd api call
    mtak_url = get_mtak_url()
    path = "{}/shutdown".format(mtak_url)

    try:
        requests_timeout = get_timeout_with_margin5(ic.mtak_timeout)
        mtak_shutdown = requests.post(path, headers=header, verify=ic.ssl_verify, timeout=requests_timeout)

        if mtak_shutdown.status_code != 204:

            msg = "REST call for ShutdownMTAK was unsuccessful. path: {} status_code: {}".format(path, mtak_shutdown.status_code)
            error_obj = create_step_error(message='Call to venue_service failed: {}'.format(path),
                                details=[mtak_shutdown.json().get("message")],
                                error_type=ErrorType.QUERY_ERROR.value,
                                error_source=ErrorSource.VENUE_SERVICE.value,
                                http_code_at_source=mtak_shutdown.status_code)
            raise StepExecutionError(msg, error_obj)

        determine_response(endpoint_name="ShutdownMTAK", query_response=mtak_shutdown)
        return "MTAK successfully shutdown"

    except StepExecutionError:
        # simply re-throw it
        raise
    except Exception as ex:
        msg = "REST call for ShutdownMTAK ({}) unsuccessful - {}".format(path, traceback.format_exc())

        error_obj = create_step_error(message='Call to venue_service failed: {}'.format(path),
                            details=[traceback.format_exc()],
                            error_type=ErrorType.QUERY_ERROR.value,
                            error_source=ErrorSource.VENUE_SERVICE.value,
                            http_code_at_source=0)
        raise StepExecutionError(str(ex), error_obj)



def DataProductsQuery(data_path, dp_status=None, ap_ids=None, time_type="ERT", start_time=None, end_time=None, timeout=ic.dp_timeout):
    '''
    This function returns all data produts that match the input parameters

    :param data_path: [Required] The data_path (which translates into the session) to query against
    :param dp_status: Data product status
    :param ap_ids: APID of data product to be retrieved
    :param time_type: The time format to use to query and to sort the resulting values.
    :param start_time: Start time for the query. String must be formatted per selected time type.
    :param end_time: End time for the query. String must be formatted per selected time type.
    :param timeout: Length of time, in seconds, to wait for database to respond before timing out.The default value is 240 seconds.
    :returns: An object containing information about the data product

    '''

    # get authorization information
    header = get_authorization_header()

    # get path for cmd api call
    path = get_dp_url()

    # get session information from data path
    try:
        session = get_session_information(data_path)
    except Exception as ex:
        msg = 'Failed to get session info for data_path: {}'.format(data_path)

        error_obj = create_step_error(message=msg,
                            details=[str(ex)],
                            error_type=ErrorType.USER_INPUT_ERROR.value,
                            error_source=ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)

        # log statement
        logger.error(msg, extra = {
            "event": EventName.DATA_PATH_CHECK.value,
            "data": error_obj
        })

        raise StepExecutionError(str(ex), error_obj)

    body_data = {'sessionId': session}

    if dp_status:
        body_data["dpStatus"] = dp_status
    if ap_ids:
        body_data["apIds"] = [ap_ids]
    if time_type:
        body_data["timeType"] = time_type
    if start_time:
        body_data["startTime"] = start_time
    if end_time:
        body_data["endTime"] = end_time

    body_data["timeout"] = timeout
    requests_timeout = get_timeout_with_margin5(timeout)


    try:
        dp_query = requests.get(path, json=body_data, headers=header, verify=ic.ssl_verify, timeout=requests_timeout)

        if dp_query.status_code != 200:

            if dp_query.status_code == 408:

                msg = "REST call for DataProductsQuery timed out. path: {}".format(path)

                error_obj = create_step_error(message=msg,
                                    details=[dp_query.json().get("message")],
                                    error_type=ErrorType.QUERY_ERROR.value,
                                    error_source=ErrorSource.VENUE_SERVICE.value,
                                    http_code_at_source=dp_query.status_code)
                raise StepExecutionError(msg, error_obj)                

            else:

                msg = "REST call for DataProductsQuery was unsuccessful. path: {} status_code: {}".format(path, dp_query.status_code)

                error_obj = create_step_error(message='Call to venue_service failed: {}'.format(path),
                                    details=[dp_query.json().get("message")],
                                    error_type=ErrorType.QUERY_ERROR.value,
                                    error_source=ErrorSource.VENUE_SERVICE.value,
                                    http_code_at_source=dp_query.status_code)
                raise StepExecutionError(msg, error_obj)
        
        determine_response(endpoint_name="DataProductsQuery", query_response=dp_query, body_data=body_data)
        return json.loads(dp_query.text)

    except StepExecutionError:
        # simply re-throw it
        raise
    except Exception as ex:
        msg = "REST call for DataProductsQuery ({}) unsuccessful - {}".format(path, traceback.format_exc())

        error_obj = create_step_error(message='Call to venue_service failed: {}'.format(path),
                            details=[traceback.format_exc()],
                            error_type=ErrorType.INGENIUM_SERVICE_ERROR.value,
                            error_source=ErrorSource.VENUE_SERVICE.value,
                            http_code_at_source=0)
        raise StepExecutionError(str(ex), error_obj)


def RealtimeEHA(data_path, channel_id, start_time, end_time, timeout=ic.eha_rt_timeout, min_results=None, time_type="ERT"):
    '''
    This function returns the latest value(s) for a given telemetry channel (EH&A)

    :param data_path: [Required] The data_path (which translates into the session) to query against
    :param channel_id: [Required] The channel ID to search for.
    :param start_time: [Required]  Start time for the query. String must be formatted per selected time type (ERT)
    :param end_time: [Required]  End time for the query. String must be formatted per selected time type (ERT).
    :param min_results:  Minimum number of results to return. Will continue to query until endTime if this is not achieved. Note that regardless of the minimum results all results found are reported.
    :returns: An object with an array of channel elements (value, timestamps, and channel id).
    '''

    # get authorization information
    header = get_authorization_header()

    # get path for cmd api call
    path = get_eha_realtime_url()

    # get session information from data path
    try:
        session = get_session_information(data_path)
    except Exception as ex:
        msg = 'Failed to get session info for data_path: {}'.format(data_path)
        
        # log statement
        logger.error(msg, extra = {
            "event": EventName.DATA_PATH_CHECK.value,
            "data": {
                "message": msg,
                "error_type": ErrorType.USER_INPUT_ERROR.value,
                "error_source": ErrorSource.EMBEDDED_CODE.value,
                "http_code_at_source": 0,
                "details": [str(ex)]
            }
        })

        error_obj = create_step_error(message=msg,
                            details=[traceback.format_exc()],
                            error_type=ErrorType.USER_INPUT_ERROR.value,
                            error_source=ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)
        raise StepExecutionError(str(ex), error_obj)

    body_data = {'sessionId': session}

    # populate body data json
    if channel_id:
        body_data["channelId"] = channel_id
    if start_time:
        body_data["startTime"] = start_time
    if end_time:
        body_data["endTime"] = end_time
    if min_results:
        body_data["minResults"] = min_results

    body_data["timeout"] = timeout
    requests_timeout = get_timeout_with_margin5(timeout)

    try:
        for idx_query_trials in range(ic.max_query_trials + 1):
            res = requests.get(path, json=body_data, headers=header, verify=ic.ssl_verify, timeout=requests_timeout)
            if res.status_code == 200:
                break
            else:
                msg = "REST call for RealtimeEHA was unsuccessful. path: {} status_code: {} idx_query_trials: {}".format(path, res.status_code, idx_query_trials)

                err_dict = res.json()
                if isinstance(err_dict, dict):
                    detail = err_dict.get("message")
                else:
                    detail = res.text
                    
                error_obj = create_step_error(message='Call to venue_service failed: {}'.format(path),
                                    details=[detail],
                                    error_type=ErrorType.QUERY_ERROR.value,
                                    error_source=ErrorSource.VENUE_SERVICE.value,
                                    http_code_at_source=res.status_code)
                                    
                logger.error(msg, extra = {
                    "event": EventName.QUERY_EHAS.value,
                    "data": error_obj
                })
                                                
                if idx_query_trials >= ic.max_query_trials:
                    raise StepExecutionError(msg, error_obj)
                else:
                    query_trial_interval = ic.query_trial_intervals[idx_query_trials]
                    logger.info(f'Will retry after {query_trial_interval} seconds')
                    time.sleep(query_trial_interval)

        determine_response(endpoint_name="RealtimeEHA", query_response=res, body_data=body_data)
        
        ehas = json.loads(res.text)
            
        # Sort by time since realtime query results from venue server are not guaranteed to be sorted.
        # The order will be latest last.
        if time_type == 'SCLK':
            sort_by = 'sclk'
        elif time_type == 'SCET':
            sort_by = 'scet'
        else:
            # default to ERT
            sort_by = 'ert'
            
        ehas_sorted = sorted(ehas, key=itemgetter(sort_by))
        
        # logger.debug(f'RealtimeEha sort_by: {sort_by} ehas: {ehas_sorted}')
        
        return ehas_sorted        

    except StepExecutionError:
        # simply re-throw it
        raise
    except Exception as ex:
        msg = "REST call for RealtimeEHA ({}) unsuccessful - {}".format(path, traceback.format_exc())

        error_obj = create_step_error(message='Call to venue_service failed: {}'.format(path),
                            details=[traceback.format_exc()],
                            error_type=ErrorType.QUERY_ERROR.value,
                            error_source=ErrorSource.VENUE_SERVICE.value,
                            http_code_at_source=0)
        raise StepExecutionError(str(ex), error_obj)

def RealtimeEHAs(data_path, channel_ids, start_time, end_time, timeout, min_results=None, time_type="ERT"):
    '''
    This function returns the latest value(s) for a given telemetry channel (EH&A)

    :param data_path: [Required] The data_path (which translates into the session) to query against
    :param channel_ids: [Required] The channel IDs to search for.
    :param start_time: [Required]  Start time for the query. String must be formatted per selected time type (ERT)
    :param end_time: [Required]  End time for the query. String must be formatted per selected time type (ERT).
    :param min_results:  Minimum number of results to return. Will continue to query until endTime if this is not achieved. Note that regardless of the minimum results all results found are reported.
    :returns: An object with an array of channel elements (value, timestamps, and channel id).
    '''

    # get authorization information
    header = get_authorization_header()

    # get path for cmd api call
    path = get_eha_realtime_multi_url()

    # get session information from data path
    try:
        session = get_session_information(data_path)
    except Exception as ex:
        msg = 'Failed to get session info for data_path: {}'.format(data_path)
        
        # log statement
        logger.error(msg, extra = {
            "event": EventName.DATA_PATH_CHECK.value,
            "data": {
                "message": msg,
                "error_type": ErrorType.USER_INPUT_ERROR.value,
                "error_source": ErrorSource.EMBEDDED_CODE.value,
                "http_code_at_source": 0,
                "details": [str(ex)]
            }
        })

        error_obj = create_step_error(message=msg,
                            details=[traceback.format_exc()],
                            error_type=ErrorType.USER_INPUT_ERROR.value,
                            error_source=ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)
        raise StepExecutionError(str(ex), error_obj)

    body_data = {'sessionId': session}

    # populate body data json
    if channel_ids:
        body_data["channelIds"] = channel_ids
    if start_time:
        body_data["startTime"] = start_time
    if end_time:
        body_data["endTime"] = end_time
    if min_results:
        body_data["minResults"] = min_results

    body_data["timeout"] = timeout
    requests_timeout = get_timeout_with_margin5(timeout)

    try:
        for idx_query_trials in range(ic.max_query_trials + 1):
            res = requests.get(path, json=body_data, headers=header, verify=ic.ssl_verify, timeout=requests_timeout)
            if res.status_code == 200:
                break
            else:
                msg = "REST call for RealtimeEHA was unsuccessful. path: {} status_code: {} idx_query_trials: {}".format(path, res.status_code, idx_query_trials)
                err_dict = res.json()
                if isinstance(err_dict, dict):
                    detail = err_dict.get("message")
                else:
                    detail = res.text
                    
                error_obj = create_step_error(message='Call to venue_service failed: {}'.format(path),
                                    details=[detail],
                                    error_type=ErrorType.QUERY_ERROR.value,
                                    error_source=ErrorSource.VENUE_SERVICE.value,
                                    http_code_at_source=res.status_code)
                                    
                logger.error(msg, extra = {
                    "event": EventName.QUERY_EHAS.value,
                    "data": error_obj
                })

                if idx_query_trials >= ic.max_query_trials:
                    raise StepExecutionError(msg, error_obj)
                else:
                    query_trial_interval = ic.query_trial_intervals[idx_query_trials]
                    logger.info(f'Will retry after {query_trial_interval} seconds')
                    time.sleep(query_trial_interval)

        determine_response(endpoint_name="RealtimeEHAs", query_response=res, body_data=body_data)
        
        ehas = json.loads(res.text)
            
        # Sort by time since realtime query results from venue server are not guaranteed to be sorted.
        # The order will be latest last.
        if time_type == 'SCLK':
            sort_by = 'sclk'
        elif time_type == 'SCET':
            sort_by = 'scet'
        else:
            # default to ERT
            sort_by = 'ert'
            
        ehas_sorted = sorted(ehas, key=itemgetter(sort_by))
        
        # logger.debug(f'RealtimeEha sort_by: {sort_by} ehas: {ehas_sorted}')
        
        return ehas_sorted        

    except StepExecutionError:
        # simply re-throw it
        raise
    except Exception as ex:
        msg = "REST call for RealtimeEHA ({}) unsuccessful - {}".format(path, traceback.format_exc())

        error_obj = create_step_error(message='Call to venue_service failed: {}'.format(path),
                            details=[traceback.format_exc()],
                            error_type=ErrorType.QUERY_ERROR.value,
                            error_source=ErrorSource.VENUE_SERVICE.value,
                            http_code_at_source=0)
        raise StepExecutionError(str(ex), error_obj)


def RealtimeEVR(data_path, start_time, end_time, evr_name=None, event_id=None, evr_level=None, time_type="ERT", min_results=None,message_filter=None, timeout=ic.evr_rt_timeout):
    '''
    This function queries the AMPCS Global LAD and returns the specified EVR(s). If no values are returned it will continual query until the timeout.

    :param data_path: [Required] The data_path (which translates into the session) to query against
    :param evr_name: Name of EVRs to retreive (either a name or pattern to match multiple names). Note that wildcards via '*' are supported.
    :param event_id: Event IDs of EVRs to retreive.
    :param evr_level: Level of EVRs to return. Note that levels are project specific and requesting a level that does not exist will return nothing. Note that wildcards via '*' are supported.
    :param start_time: [Required] Start time for the query. String must be formatted per selected time type (ERT).
    :param end_time: [Required] End time for the query. String must be formatted per selected time type (ERT).
    :param min_results:  Minimum number of results to return. Will continue to query until endTime if this is not achieved. Note that regardless of the minimum results all results found are reported.
    :returns: An object with an array of evr elements
    '''

    # get authorization information
    header = get_authorization_header()

    # get path for cmd api call
    path = get_evr_realtime_url()

    # get session information from data path
    try:
        session = get_session_information(data_path)
    except Exception as ex:
        msg = 'Failed to get session info for data_path: {}'.format(data_path)
        
        # log statement
        logger.error(msg, extra = {
            "event": EventName.DATA_PATH_CHECK.value,
            "data": {
                "message": msg,
                "error_type": ErrorType.USER_INPUT_ERROR.value,
                "error_source": ErrorSource.EMBEDDED_CODE.value,
                "http_code_at_source": 0,
                "details": [str(ex)]
            }
        })

        error_obj = create_step_error(message=msg,
                            details=[traceback.format_exc()],
                            error_type=ErrorType.USER_INPUT_ERROR.value,
                            error_source=ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)
        raise StepExecutionError(str(ex), error_obj)

    body_data = {'sessionId': session}

    # populate body data json
    if evr_name:
        body_data["evrName"] = evr_name
    if event_id:
        try:
            body_data["eventId"]= int(event_id)
        except Exception as ex:
            msg = "Field 'EVR ID' is a non-integer value: {}. Please use an integer value.".format(event_id)
            error_obj = create_step_error(message=msg,
                                details=[traceback.format_exc()],
                                error_type=ErrorType.USER_INPUT_ERROR.value,
                                error_source=ErrorSource.EMBEDDED_CODE.value,
                                http_code_at_source=0)
            logger.error(msg, extra = {
                "event": EventName.QUERY_EVRS.value,
                "data": error_obj
            })
            raise StepExecutionError(msg, error_obj)   
    if evr_level:
        body_data["evrLevel"] = evr_level
    if start_time:
        body_data["startTime"] = start_time
    if end_time:
        body_data["endTime"] = end_time
    if min_results:
        body_data["minResults"] = min_results

    body_data["timeout"] = timeout
    requests_timeout = get_timeout_with_margin5(timeout)

    try:
        for idx_query_trials in range(ic.max_query_trials + 1):
            evrs = requests.get(path, json=body_data, headers=header, verify=ic.ssl_verify, timeout=requests_timeout)
            if evrs.status_code == 200:
                break
            else:
                msg = "REST call for RealtimeEVR was unsuccessful. path: {} status_code: {}  idx_query_trials: {}".format(path, evrs.status_code, idx_query_trials)

                error_obj = create_step_error(message='Call to venue_service failed: {}'.format(path),
                                    details=[evrs.json().get("message")],
                                    error_type=ErrorType.QUERY_ERROR.value,
                                    error_source=ErrorSource.VENUE_SERVICE.value,
                                    http_code_at_source=evrs.status_code)
                logger.error(msg, extra = {
                    "event": EventName.QUERY_EVRS.value,
                    "data": error_obj
                })            
                if idx_query_trials >= ic.max_query_trials:
                    raise StepExecutionError(msg, error_obj)
                else:
                    query_trial_interval = ic.query_trial_intervals[idx_query_trials]
                    logger.info(f'Will retry after {query_trial_interval} seconds')
                    time.sleep(query_trial_interval)

        determine_response(endpoint_name="RealtimeEVR", query_response=evrs, body_data=body_data)
        evrs = json.loads(evrs.text)

    except StepExecutionError:
        # simply re-throw it
        raise
    except Exception as ex:
        msg = "REST call for RealtimeEVR ({}) unsuccessful - {}".format(path, traceback.format_exc())

        error_obj = create_step_error(message='Call to venue_service failed: {}'.format(path),
                            details=[traceback.format_exc()],
                            error_type=ErrorType.QUERY_ERROR.value,
                            error_source=ErrorSource.VENUE_SERVICE.value,
                            http_code_at_source=0)
        raise StepExecutionError(str(ex), error_obj)

    # If there is a message filter iterate on the results to apply it
    evrs_filtered=[]
    for evr in evrs:
        # If no filter - just append the results
        if message_filter is None:
            evrs_filtered.append(evr)
        elif message_filter in evr["evrMessage"]:
            evrs_filtered.append(evr)

    # Sort by time since realtime query results from venue server are not guaranteed to be sorted.
    # The order will be latest last.
    if time_type == 'SCLK':
        sort_by = 'sclk'
    elif time_type == 'SCET':
        sort_by = 'scet'
    else:
        # default to ERT
        sort_by = 'ert'
        
    evrs_sorted = sorted(evrs_filtered, key=itemgetter(sort_by))
    
    return evrs_sorted



class EhaResponse(object):

    def __init__(self, input_entries, translated_start_time, translated_end_time, start_time, end_time):
        
        self.eha_response = {
            "venue_id": ic.venue_id,
            "venue_name": ic.venue_name,
            "venue_ampcs_address": ic.venue_service_address,
            "translated_start_time": translated_start_time,
            "translated_end_time": translated_end_time,
            "query_start_time": start_time,
            "query_end_time": end_time,
            "entries": input_entries
        }    

        update_response_structure = {
            "dn": "",
            "eu": 0,
            "session_id": 0,
            "channel_status": "",
            "sclk": "",
            "ert": "",
            "scet": "",
            "actual_value": "",
            "verification_status": "PENDING"
        }

        for entry in self.eha_response["entries"]:
            entry.update(update_response_structure)
        
        #self.eha_response["entries"] = input_entries
        
    def update_eha_entry(self, index, eha, channel_id, verification_status, actual_value):
        
        entry = self.eha_response["entries"][index]


        formatted_response_structure = {
            "dn": "" if eha.get("dn") is None else str(eha.get("dn")),
            "eu": 0 if eha.get("eu") is None else eha.get("eu"),
            "session_id": 0 if eha.get("sessionId") is None else eha.get("sessionId"),
            "channel_status": "" if eha.get("channelStatus") is None else eha.get("channelStatus"),
            "sclk": "" if eha.get("sclk") is None else eha.get("sclk"),
            "ert": "" if eha.get("ert") is None else eha.get("ert"),
            "scet": "" if eha.get("scet") is None else eha.get("scet"),
            "verification_status": verification_status,
            "actual_value": str(actual_value)
        }

        entry.update(formatted_response_structure)

    def return_intermediate_response(self):

        return self.eha_response

class EvrResponse(object):

    def __init__(self, input_entries, translated_start_time, translated_end_time, start_time, end_time): 
        update_response_structure = {
            "verification_status": "PENDING",
            "total_count": 0,
            "evr_data": []            
        }

        for entry in input_entries:
            entry.update(update_response_structure)        

        self.evr_response = {
            "venue_id": ic.venue_id,
            "venue_name": ic.venue_name,
            "venue_ampcs_address": ic.venue_service_address,
            "translated_start_time": translated_start_time,
            "translated_end_time": translated_end_time,
            "query_start_time": start_time,
            "query_end_time": end_time,
            "entries": input_entries
        } 

    def verify_response(self, entry):
        if entry["verification_condition"] == "EXISTS":
            if entry["total_count"] > 0:
                entry["verification_status"] = "PASS"
            else:
                entry["verification_status"] = "FAIL"

        elif entry['verification_condition'] == "DOES_NOT_EXIST":
            if entry["total_count"] > 0:
                entry["verification_status"] = "FAIL"
            else:
                entry["verification_status"] = "PASS"


    def update_evr_entry(self, index, evrs, total_count):
        entry = self.evr_response["entries"][index]
        entry["total_count"] = total_count
        self.verify_response(entry)

        formatted_evrs = []
        for evr in evrs:
            formatted_response_structure = {
                "evr_name": evr.get("evrName", ""),
                "session_id": evr.get("sessionId", 0),
                "vcid": evr.get("vcId", 0),
                "event_id": evr.get("eventId", 0),
                "evr_level": evr.get("evrLevel", ""),
                "from_sse": evr.get("fromSSE", False),
                "evr_message": evr.get("evrMessage", ""),
                "evr_module": evr.get("evrModule", ""),
                "sclk": evr.get("sclk", 0),
                "ert": evr.get("ert", ""),
                "scet": evr.get("scet", ""),
                "is_recorded": evr.get("isRecorded", False)
            }
            formatted_evrs.append(formatted_response_structure)

        entry["evr_data"] = formatted_evrs

    def return_intermediate_response(self):

        return self.evr_response


class DpResponse(object):

    def __init__(self, input_entries, translated_start_time, translated_end_time, start_time, end_time):
        update_response_structure = {
            "verification_status": "PENDING",
            "total_count": 0,
            "products": []
        }

        for entry in input_entries:
            entry.update(update_response_structure)

        self.dp_response = {
            "venue_id": ic.venue_id,
            "venue_name": ic.venue_name,
            "venue_ampcs_address": ic.venue_service_address,
            "translated_start_time": translated_start_time,
            "translated_end_time": translated_end_time,
            "query_start_time": start_time,
            "query_end_time": end_time,
            "entries": input_entries            
        }

    def verify_response(self, entry):

        if entry["verification_condition"] == "GREATER_THAN":
            if entry["total_count"] > entry["verification_value"]:
                entry["verification_status"] = "PASS"
            else:
                entry["verification_status"] = "FAIL"

        if entry["verification_condition"] == "LESS_THAN":
            if entry["total_count"] < entry["verification_value"]:
                entry["verification_status"] = "PASS"
            else:
                entry["verification_status"] = "FAIL"

        if entry["verification_condition"] == "GREATER_THAN_OR_EQUAL":
            if entry["total_count"] >= entry["verification_value"]:
                entry["verification_status"] = "PASS"
            else:
                entry["verification_status"] = "FAIL"

        if entry["verification_condition"] == "LESS_THAN_OR_EQUAL":
            if entry["total_count"] <= entry["verification_value"]:
                entry["verification_status"] = "PASS"
            else:
                entry["verification_status"] = "FAIL"

        if entry["verification_condition"] == "EQUAL":
            if entry["total_count"] == entry["verification_value"]:
                entry["verification_status"] = "PASS"
            else:
                entry["verification_status"] = "FAIL"

        if entry["verification_condition"] == "RECORD":
            if entry["total_count"]:
                entry["verification_status"] = "PASS"
            else:
                entry["verification_status"] = "FAIL"

        
    def update_dp_entry(self, index, dps, total_count): 

        entry = self.dp_response["entries"][index]
        entry["total_count"] = total_count 
        self.verify_response(entry)

        formatted_dps = []

        for dp in dps:
            formatted_response_structure = {
                "session_id": dp.get("sessionId", 0),
                "vcid": dp.get("vcId", 0),
                "dp_status": dp.get("dpStatus", ""),
                "apid": dp.get("apId", 0),
                "apid_product_type": dp.get("apIdProductType", ""),
                "file_path": dp.get("filePath", ""),
                "file_size": dp.get("fileSize", 0),
                "creation_time": dp.get("creationTime", ""),
                "sclk": dp.get("sclk", ""),
                "ert": dp.get("ert", ""),
                "scet": dp.get("scet", "") 
            }

            formatted_dps.append(formatted_response_structure)
        
        entry["products"] = formatted_dps

    def return_intermediate_response(self):

        return self.dp_response

class Bus1553Response(object):

    def __init__(self, input_entries, translated_start_time, translated_end_time, start_time, end_time):
        
        self.bus_response = {
            "venue_id": ic.venue_id,
            "venue_name": ic.venue_name,
            "venue_ampcs_address": ic.venue_service_address,
            "translated_start_time": translated_start_time,
            "translated_end_time": translated_end_time,
            "query_start_time": start_time,
            "query_end_time": end_time,
            "entries": input_entries
        }    

        update_response_structure = {
            "rti": 0,
            "bus_name": "",
            "error_status": "",
            "data_type": "",
            "data_value": "",
            "converted_value": "",
            "actual_value": "",
            "dictionary": "",
            "log_file": "",
            "sclk": "",
            "scet": "",
            "verification_status": "PENDING"
        }

        for entry in self.bus_response["entries"]:
            entry.update(update_response_structure)
        

    def update_bus_entry(self, index, bus_res, var_name, verification_status, actual_value):

        entry = self.bus_response["entries"][index]

        formatted_response_structure = {
            "rti": 0 if bus_res.get("rti") is None else bus_res.get("rti"),
            "bus_name": "" if bus_res.get("bus_name") is None else bus_res.get("bus_name"),
            "error_status": "" if bus_res.get("error_status") is None else bus_res.get("error_status"),
            "data_type": "" if bus_res.get("data_type") is None else bus_res.get("data_type"),
            "data_value": "" if bus_res.get("data_value") is None else bus_res.get("data_value"),
            "converted_value": "" if bus_res.get("converted_value") is None else bus_res.get("converted_value"),
            "actual_value": actual_value,
            "dictionary": "" if bus_res.get("dictionary") is None else bus_res.get('dictionary'),
            "log_file": "" if bus_res.get("log_file") is None else bus_res.get("log_file"),
            "sclk": "" if bus_res.get("time_sclk") is None else str(bus_res.get("time_sclk")),
            "scet": "" if bus_res.get("time_scet") is None else bus_res.get('time_scet'),
            "verification_status": verification_status
        }

        entry.update(formatted_response_structure)

    def update_entry_verification_status(self, index, verification_status):
        
        entry = self.bus_response["entries"][index]
        entry.update({"verification_status": verification_status})
        
    def return_intermediate_response(self):

        return self.bus_response


class CustomScriptResponse(object):

    def __init__(self, step_input):
        # add "value" field to all outputs
        # Note that this changes the values in the dictionary of step_input["outputs"].
        for output in step_input.get("outputs"):
            output.update({"value": ""})

        self.script_response = {
            "script_name": step_input.get("script_name"),
            "script_path": step_input.get("script_path"),
            "description": step_input.get("description"),
            "hash": step_input.get("hash"),
            "status": step_input.get("status"),
            "timeout": step_input.get("timeout"),
            "inputs": step_input.get("inputs"),
            "entries": step_input.get("entries"),
            "outputs": step_input.get("outputs"),
            "output_array": step_input.get("output_array"),
            "output_summary": "",
            "venue_id": ic.venue_id,
            "venue_name": ic.venue_name,
            "venue_ampcs_address": ic.venue_service_address,            
            "custom_script_status": "PENDING",
            "log_file_local_path": "",
            "log_file_url": ""
        }
    
    def update_logfile_url(self, logfile_url):
        
        # this is the link to the s3 object 
        self.script_response["log_file_url"] = logfile_url
 
    def update_outputs_with_results(self, script_status_info):

        output_object = script_status_info.get("custom_script_outputs", {})        
        
        ### entries
        entries = output_object.get("entries", [])
        script_entries = self.script_response.get("entries", [])
        
        for i, entry in enumerate(entries):
            if i > len(script_entries)-1:
                logger.warning("more entries returned than expected. Max count: {} Actual count: {}".format(len(script_entries), len(entries)))
                break
            script_entry = script_entries[i]
            
            # update entry verification status
            script_entry["verification_status"] = entry.get("verification_status")

            entry_outputs = entry.get("entry_outputs", {})
            script_entry_outputs = script_entry.get("entry_outputs", [])
            script_entry_outputs_map = {script_entry_output["name"] : i for i, script_entry_output in enumerate(script_entry_outputs)}
            for name, value in entry_outputs.items():
                idx = script_entry_outputs_map.get(name)
                if idx is None:
                    logger.warning("Entry output was not found. name: {}".format(name))
                else:
                    script_entry_output = script_entry_outputs[idx]
                    script_entry_output.update({"value": value})
                            
            entry_output_array = entry.get("entry_output_array", [])
            script_entry_output_array = script_entry.get("entry_output_array", {})
            script_entry_output_array_outputs = script_entry_output_array.get("outputs", [])
            script_entry_output_array_outputs_map = {script_entry_output_array_output["name"] : i for i, script_entry_output_array_output in enumerate(script_entry_output_array_outputs)}
            # reset values
            for script_entry_output_array_output in script_entry_output_array_outputs:
                script_entry_output_array_output["values"] = []
            # populate values        
            for entry_output_array_fields in entry_output_array:
                for name, value in entry_output_array_fields.items():
                    idx = script_entry_output_array_outputs_map.get(name)
                    if idx is None:
                        logger.warning("Entry output array field was not found. name: {}".format(name))
                    else:
                        script_entry_output_array_output = script_entry_output_array_outputs[idx]
                        script_entry_output_array_output["values"].append(value)
                        
        ### outputs
        outputs = output_object.get("outputs", {})
        script_outputs = self.script_response.get("outputs", [])
        script_outputs_map = {script_output["name"] : i for i, script_output in enumerate(script_outputs)}
        for name, value in outputs.items():
            idx = script_outputs_map.get(name)
            if idx is None:
                logger.warning("output was not found. name: {}".format(name))
            else:
                script_output = script_outputs[idx]
                script_output.update({"value": value})
                
        ### output array
        output_array = output_object.get("output_array", [])
        script_output_array = self.script_response.get("output_array", {})
        script_output_array_outputs = script_output_array.get("outputs", [])
        script_output_array_outputs_map = {script_output_array_output["name"] : i for i, script_output_array_output in enumerate(script_output_array_outputs)}
        # reset values
        for script_output_array_output in script_output_array_outputs:
            script_output_array_output["values"] = []
        # populate values        
        for output_array_fields in output_array:
            for name, value in output_array_fields.items():
                idx = script_output_array_outputs_map.get(name)
                if idx is None:
                    logger.warning("Output array field was not found. name: {}".format(name))
                else:
                    script_output_array_output = script_output_array_outputs[idx]
                    script_output_array_output["values"].append(value)

        # output_summary
        self.script_response["output_summary"] = output_object.get("output_summary", "")

        # update the following fields
        self.script_response["custom_script_status"] = script_status_info.get("custom_script_status")
        self.script_response["log_file_local_path"] = script_status_info.get("logfile_path")

    def return_intermediate_response(self):

        return self.script_response

    def return_script_outputs(self):

        return self.script_response.get("outputs")

    def return_script_status(self):

        return self.script_response.get("custom_script_status")


def query_bus_1553(start_time, end_time, variables, timeout, time_type):
    
    # get authorization information
    header = get_authorization_header()

    # get path for cmd api call
    path = get_query_1553_url()

    body_data = {}

    if start_time:
        body_data["start_time"] = start_time
    if end_time:
        body_data["end_time"] = end_time
    if variables:
        body_data["variables"] = variables
    if time_type:
        body_data["time_type"] = time_type
    
    # bus 1553 venue server endpoint does not have a timeout field.
    try:
        bus_logs = requests.get(path, json=body_data, headers=header, verify=ic.ssl_verify, timeout=ic.bus_1553_timeout)
        
        if bus_logs.status_code != 200:
            
            msg = "REST call for Bus1553Logs was unsuccessful. path: {} status_code: {}".format(path, bus_logs.status_code)

            error_obj = create_step_error(message='Call to venue_service failed: {}'.format(path),
                                details=[bus_logs.json().get("message")],
                                error_type='INGENIUM_SERVICE_ERROR',
                                error_source='VENUE_SERVICE',
                                http_code_at_source=bus_logs.status_code)
            raise StepExecutionError(msg, error_obj)
        
    except StepExecutionError:
        raise
    except Exception as ex:
        msg = "REST call for Bus1553Logs ({}) unsuccessful - {}".format(path, traceback.format_exc())

        error_obj = create_step_error(message='Call to venue_service failed: {}'.format(path),
                            details=[traceback.format_exc()],
                            error_type='INGENIUM_SERVICE_ERROR',
                            error_source='VENUE_SERVICE',
                            http_code_at_source=0)
        raise StepExecutionError(str(ex), error_obj)        

    return json.loads(bus_logs.text)


def parse_to_doy(time_input_value):
    
    if time_input_value is not None:
        time_input_value = time_input_value.strip()

    time_value = None
    
    try:
        reference_time = get_reference_time(time_input_value)
        if reference_time:
            time_value = datetime.strptime(reference_time, '%Y-%m-%dT%H:%M:%S.%fZ')
        else:
            for time_format in ['%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S.%fZ', '%Y-%m-%dT%H:%M:%S', '%Y-%jT%H:%M:%S']:
                try:
                    time_value = datetime.strptime(time_input_value, time_format)
                    # if time_input_value was parsed successfully, we are done
                    break
                except ValueError:
                    pass            

    except:
        msg = "There was an error parsing time value for: {}".format(time_input_value)
        # log statement
        error_obj = create_step_error(message=msg,
                            details=[],
                            error_type=ErrorType.USER_INPUT_ERROR.value,
                            error_source=ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)

        logger.error(msg, extra = {
            "event": EventName.TIME_VALIDATION.value,
            "data": error_obj
        })

        raise StepExecutionError(msg, error_obj)
        

    logger.info("Time value parsed: {}".format(time_value))

    if time_value is None:
        msg = "Failed to parse time value: {}".format(time_input_value)

        error_obj = create_step_error(message=msg,
                            details=[],
                            error_type=ErrorType.USER_INPUT_ERROR.value,
                            error_source=ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)

        logger.error(msg, extra = {
            "event": EventName.TIME_VALIDATION.value,
            "data": error_obj
        })

        raise StepExecutionError(msg, error_obj)

    # convert time value to DOY format 
    try:
        doy_time = time_value.strftime('%Y-%jT%H:%M:%S')
    except:
        msg = "The time input was successfully parsed but could not be formatted to DOY: {}".format(time_value)
        # log statement
        error_obj = create_step_error(message=msg,
                            details=[],
                            error_type=ErrorType.USER_INPUT_ERROR.value,
                            error_source=ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)

        logger.error(msg, extra = {
            "event": EventName.TIME_VALIDATION.value,
            "data": error_obj
        })

        raise StepExecutionError(msg, error_obj)

    return doy_time

def start_custom_script(step_input):


    # get authorization information
    header = get_authorization_header()
    path = get_custom_script_start_url()

    # construct input json
    try:
        cs_inputs_obj = CustomScriptInputs(step_input)
    except StepExecutionError:
        raise

    body_data = {}

    body_data["scriptName"] = step_input.get("script_name", "")
    body_data["scriptPath"] = step_input.get("script_path", "")
    body_data["scriptHash"] = step_input.get("hash", "")
    body_data["inputs"] = cs_inputs_obj.input_json
    body_data["outputs"] = cs_inputs_obj.output_json

    logger.debug("inputs: {}".format(body_data["inputs"]))
    logger.debug("outputs: {}".format(body_data["outputs"]))        
    
    try:
        start_response = requests.post(path, json=body_data, headers=header, verify=ic.ssl_verify, timeout=ic.custom_script_timeout)
        
        if start_response.status_code != 200:
            
            msg = "REST call for Custom Script start was unsuccessful. path: {} status_code: {}".format(path, start_response.status_code)

            error_obj = create_step_error(message='Call to venue_service failed: {}'.format(path),
                                details=[start_response.json().get("message")],
                                error_type=ErrorType.VENUE_SERVICE_ERROR.value,
                                error_source=ErrorSource.VENUE_SERVICE.value,
                                http_code_at_source=start_response.status_code)
            raise StepExecutionError(msg, error_obj)
    except StepExecutionError:
        raise
    except Exception as ex:
        msg = "REST call for Custom Script start ({}) unsuccessful - {}".format(path, traceback.format_exc())

        error_obj = create_step_error(message=msg,
                            details=[traceback.format_exc()],
                            error_type=ErrorType.VENUE_SERVICE_ERROR.value,
                            error_source=ErrorSource.VENUE_SERVICE.value,
                            http_code_at_source=0)
        raise StepExecutionError(str(ex), error_obj)     
    
    logger.info(start_response.text)
    return json.loads(start_response.text)

def get_script_status(scriptRunId):

    header = get_authorization_header()
    path = get_custom_script_status_url()
   
    if scriptRunId:
        path = path + f'/{scriptRunId}'

    return requests.get(path, headers=header, verify=ic.ssl_verify, timeout=ic.custom_script_timeout)


def halt_script(scriptRunId):

    header = get_authorization_header()
    path = halt_custom_script_url()

    if scriptRunId:
        path = path + f'/{scriptRunId}/halt'

    try:
        # custom script timeout constant is long, halting a script is a quick process so we will use ic.rest_timeout which is 20 secs.
        halt_script_response = requests.post(path, headers=header, verify=ic.ssl_verify, timeout=ic.rest_timeout)
        
        if halt_script_response.status_code != 204:
            
            msg = "REST call for Custom Script halt was unsuccessful. path: {} status_code: {}".format(path, halt_script_response.status_code)

            error_obj = create_step_error(message='Call to venue_service failed: {}'.format(path),
                                details=[halt_script_response.json().get("message")],
                                error_type=ErrorType.VENUE_SERVICE_ERROR.value,
                                error_source=ErrorSource.VENUE_SERVICE.value,
                                http_code_at_source=halt_script_response.status_code)
            raise StepExecutionError(msg, error_obj)
    except StepExecutionError:
        raise
    except Exception as ex:
        msg = "REST call for Custom Script halt ({}) unsuccessful - {}".format(path, traceback.format_exc())

        error_obj = create_step_error(message=msg,
                            details=[traceback.format_exc()],
                            error_type=ErrorType.VENUE_SERVICE_ERROR.value,
                            error_source=ErrorSource.VENUE_SERVICE.value,
                            http_code_at_source=0)
        raise StepExecutionError(str(ex), error_obj)  

    # returns "204" if nominal response. 
    return halt_script_response.status_code

def construct_object_name(file_name, script_run_id):

    now = datetime.utcnow()
    # ex: 2020-09-28
    date_stamp = now.strftime("%Y-%m-%d")

    shortened_file_path = file_name.split("/")[-1]

    object_name = "custom_scripts/{}/{}/{}".format(date_stamp, script_run_id, shortened_file_path)
    logger.info("Constructed object name: {}".format(object_name))
    return object_name

def upload_file_to_fileserver(file_name, script_run_id):

    bucket = ic.media_bucket

    # construct path for filename : media_bucket/custom_scripts/datetime/file.tar.gz
    fileserver_object_name = construct_object_name(file_name, script_run_id)

    # Upload the file
    # Due to how boto3 works, the AWS access key, AWS secret access key, and default region are set
    # as environment variables in the execution server container as: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
    # and `AWS_DEFAULT_REGION`. These variables are used internally by boto3 to authenticate the client() request
    # therefore, they do not explicitly need to be passed to the client() function as arguments

    try:
        fileserver = boto3.client('s3', endpoint_url=ic.file_server_api_host)
        # TODO: make this configurable.
        # Need to use below for Minio. Note that boto3 does not allow underscore in the host name.
        # fileserver = boto3.client('s3', endpoint_url='http://fileservering:9000')
      
        response = fileserver.upload_file(file_name, bucket, fileserver_object_name)
        full_fileserver_object_name = "{}/{}".format(ic.media_bucket, fileserver_object_name)
        logger.info("Fileserver object name: {}".format(full_fileserver_object_name))
    except ClientError as e:
        raise Exception("There was an issue uploading file to fileserver: {}".format(str(e)))

    # we will need the object name to retrieve the presigned url
    return full_fileserver_object_name

def process_cs_files(logfile_partial_url, script_run_id, custom_script_response=None):

    header = get_cs_files_authorization_header()
    path = get_custom_script_tar(logfile_partial_url)
    logger.info("Constructed custom_scripts/files path: {}".format(path))

    try:
        custom_script_logs = requests.get(path, headers=header, verify=ic.ssl_verify, timeout=ic.custom_script_timeout)
        if custom_script_logs.status_code != 200:
            
            msg = "REST call for Custom Script halt was unsuccessful. path: {} status_code: {}".format(path, custom_script_logs.status_code)

            error_obj = create_step_error(message='Call to venue_service failed: {}'.format(path),
                                details=[custom_script_logs.json().get("message")],
                                error_type=ErrorType.VENUE_SERVICE_ERROR.value,
                                error_source=ErrorSource.VENUE_SERVICE.value,
                                http_code_at_source=custom_script_logs.status_code)
            raise StepExecutionError(msg, error_obj)
    except StepExecutionError:
        raise
    except Exception as ex:
        msg = "REST call for Custom Script halt ({}) unsuccessful - {}".format(path, traceback.format_exc())

        error_obj = create_step_error(message=msg,
                            details=[traceback.format_exc()],
                            error_type=ErrorType.VENUE_SERVICE_ERROR.value,
                            error_source=ErrorSource.VENUE_SERVICE.value,
                            http_code_at_source=0)
        raise StepExecutionError(str(ex), error_obj)   

    # check if /tmp/custom_script_logs/script_run_id exists. If not create it.
    base_temp_dir = "/tmp/custom_script_logs" 
    # Add script_run_id to the path
    base_temp_script_dir = os.path.join(base_temp_dir, script_run_id)

    if not os.path.exists(base_temp_script_dir):
        logger.info("Base temporary script log directory was not found, creating it!")
        # TODO: error capturing here
        try:
            os.makedirs(base_temp_script_dir, exist_ok=True)
        except Exception as e:
            msg = f"There was an error making the temporary custom script directory: {base_temp_script_dir}"
            error_obj = create_step_error(message=msg,
                                details=[str(e)],
                                error_type=ErrorType.QUERY_ERROR.value,
                                error_source=ErrorSource.EMBEDDED_CODE.value,
                                http_code_at_source=400)
            raise StepExecutionError(msg, error_obj)  

    # store downloaded tarball locally. example filename: "/tmp/custom_script_logs/script_run_id/script_run_id.tar.gz"
    file_name_with_tar_extension = script_run_id + ".tar.gz"
    temp_cs_log_file = os.path.join(base_temp_script_dir, file_name_with_tar_extension)
    logger.info("Storing tar.gz locally in dir: {}".format(temp_cs_log_file))

    try:
        open(temp_cs_log_file, "wb").write(custom_script_logs.content)
        logger.info("Tarball stored successfully!")
    except Exception as e:
        msg = "There was an issue saving the logfile tarball locally."

        error_obj = create_step_error(message=msg,
                            details=[str(e)],
                            error_type=ErrorType.QUERY_ERROR.value,
                            error_source=ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=400)
        raise StepExecutionError(msg, error_obj)  

    top_level_folder = ""
    file_name_set = set()
    output_json = {}
    if custom_script_response is not None:
        # extract the tarball locally
        try:
            extract_dir = os.path.dirname(temp_cs_log_file)  # same directory as tarball
            with tarfile.open(temp_cs_log_file, "r:gz") as tar:
                files = tar.getnames()
                logger.info("Tarball contains %d files: %s", len(files), files)
                tar.extractall(path=extract_dir)
            logger.info("Tarball extracted successfully! Extracted to %s", extract_dir)
            # Get the top-level folder created by the tarball
            if len(files) > 0:
                top_level_folder = os.path.join(extract_dir, files[0].split("/")[0])
                logger.info("Extracted top level folder: %s", top_level_folder)
            else:
                logger.warning(f"No file in tar file: {temp_cs_log_file}")
        except Exception as e:
            msg = "There was an issue extracting the logfile tarball."
            error_obj = create_step_error(
                message=msg,
                details=[str(e)],
                error_type=ErrorType.QUERY_ERROR.value,
                error_source=ErrorSource.EMBEDDED_CODE.value,
                http_code_at_source=400
            )
            raise StepExecutionError(msg, error_obj)
        
        try:
            output_json_path = os.path.join(top_level_folder, 'output.json')
            if top_level_folder and os.path.isfile(output_json_path):
                with open(output_json_path, 'r') as file:
                    output_json = json.load(file)
            else:
                msg = f'custom script output file was not found at: {output_json_path}'
                logger.warning(msg)
        except Exception as e:
            msg = f'Error when parsing output.json of custom script. path: {output_json_path}'
            logger.warning(msg)
            
        try:
            script_response = custom_script_response.script_response

            # List only files in that root folder
            if top_level_folder:
                file_name_set = {
                    f for f in os.listdir(top_level_folder)
                    if os.path.isfile(os.path.join(top_level_folder, f))
                }
            
            logger.info("Files in root of extracted folder: %s", file_name_set)
            # map from file name to URL in fileserver
            uploaded_file_map = dict()

            # Collect names where type matches FILE, IMAGE, or SERIES
            file_types = {'FILE', 'IMAGE', 'SERIES'}

            # Top-level outputs
            outputs = script_response.get('outputs', [])
            for output in outputs:
                if output.get('type') in file_types:
                    name = output.get('name', '')
                    value = output.get('value', '')

                    # If type is SERIES, force value to series.json
                    if output.get('type') == 'SERIES':
                        value = 'series.json'
                        output['value'] = value  # keep the field consistent

                    if value in file_name_set:
                        if value in uploaded_file_map:
                            # file has been already uploaded. Replace file name with URL
                            logger.warning(f'File ({value}) has been already uploaded before output: {name}')
                            output['value'] = uploaded_file_map[value]
                        else:
                            file_path = os.path.join(top_level_folder, value)
                            uploaded_url = upload_file_to_fileserver(file_path, script_run_id)
                            # replace file name with URL
                            output['value'] = uploaded_url
                            uploaded_file_map[value] = uploaded_url

            # Entry outputs from each entry
            entries = script_response.get('entries', [])
            for entry in entries:
                entry_outputs = entry.get('entry_outputs', [])
                for entry_output in entry_outputs:
                    if entry_output.get('type') in file_types:
                        name = entry_output.get('name', '')
                        value = entry_output.get('value', '')

                        # If type is SERIES, force value to series.json
                        if entry_output.get('type') == 'SERIES':
                            value = 'series.json'
                            entry_output['value'] = value  # keep the field consistent

                        if value in file_name_set:
                            if value in uploaded_file_map:
                                # file has been already uploaded. Replace file name with URL
                                logger.warning(f'File ({value}) has been already uploaded before entry_output: {name}')
                                entry_output['value'] = uploaded_file_map[value]
                            else:
                                file_path = os.path.join(top_level_folder, value)
                                uploaded_url = upload_file_to_fileserver(file_path, script_run_id)
                                # replace file name with URL
                                entry_output['value'] = uploaded_url
                                uploaded_file_map[value] = uploaded_url
        except Exception as e:
            msg = "Error when uploading individual files of custom script"
            error_obj = create_step_error(
                message=msg,
                details=[str(e)],
                error_type=ErrorType.QUERY_ERROR.value,
                error_source=ErrorSource.EMBEDDED_CODE.value,
                http_code_at_source=400
            )
            raise StepExecutionError(msg, error_obj)

    # ASSUME the following config variables are present in ingenium config: access_key, secret_key, and media_bucket
    logger.info("Uploading tarball: {}".format(file_name_with_tar_extension))
    object_name = ""
    try:
        object_name = upload_file_to_fileserver(temp_cs_log_file, script_run_id)
    except Exception as e:
        logger.warning(str(e))       
    finally:
        # delete logfile tarball from local drive (to keep directory clean)
        # if you need reference to this tarball, it can be found in the GDS host under /tmp/cs/scriptRunId
        os.remove(temp_cs_log_file)
        logger.info("Temp log file successfully removed: {}".format(temp_cs_log_file))

    return object_name, output_json

class CustomScriptInputs(object):
    
    def __init__(self, step_input):
        self.step_input = step_input
        
        self.input_json = OrderedDict({
            "username": "",
            "states": {
                "variables": ic.variables,
                "channel_variables": ic.channel_variables,
                "manual_input_variables": ic.manual_input_variables,
                "mil_1553_variables": ic.mil_1553_variables
            }
        })
        self.output_json = OrderedDict({
            "custom_script_status": "PENDING",
            "states": {
                "variables": ic.variables,
                "channel_variables": ic.channel_variables,
                "manual_input_variables": ic.manual_input_variables,
                "mil_1553_variables": ic.mil_1553_variables
            }
        })
        
        self.construct_input_json()
        self.construct_output_json()

    def construct_input_json(self):

        # convert inputs from array format to object format
        self.input_json["inputs"] = self.parse_input_types(inputs=self.step_input.get("inputs", []))

        # cycle through entry input fields
        entries = []
        self.input_json["entries"] = entries
        for e in self.step_input.get("entries", []):
            entry = OrderedDict()
            entry["entry_inputs"] = self.parse_input_types(inputs=e["entry_inputs"])
            entries.append(entry)

    def construct_output_json(self):

        self.output_json["inputs"] = self.parse_input_types(inputs=self.step_input.get("inputs", []))
        
        # parse entries
        self.output_json["entries"] = self.parse_entry_type(entries=self.step_input.get("entries", []))        

        # parse outputs
        self.output_json["outputs"] = self.parse_output_types(outputs=self.step_input.get("outputs", []))

        # initialize output array with an empty array 
        self.output_json["output_array"] = []

    def parse_input_types(self, inputs):

        structure = OrderedDict()

        for input in inputs:
            name = input.get("name")
            type = input.get("type")
            # if no value, treat it as None
            value = get_dict_value_default_none(input, "value")
            default_value = get_dict_value_default_none(input, "default_value")
            required = input.get("required")

            logger.debug(f"name: {name} type: {type} required: {required} value: {value} default_value: {default_value}")

            # if value is not defined for BOOL type, set it as "false" or "true" based on default_value
            # See ING-3875
            if type == "BOOL" and value is None:
                if default_value is None:
                    input["value"] = "false"
                    value = "false"
                else:
                    if str(default_value).lower() == "true":
                        input["value"] = "true"
                        value = "true"
                    else:
                        input["value"] = "false"
                        value = "false"

            # if the input is not required and a value is not provided, 
            # use empty value and continue to the next input
            if required == "NO" and value is None:
                structure[name] = ""
                continue 

            # if the input is required and no value is provided, error returned.
            # value is required 
            if required == "YES" and value is None:
                msg = "A value is required for input name: {} but none was found".format(name)
                error_obj = create_step_error(message=msg,
                                    details=[],
                                    error_type=ErrorType.USER_INPUT_ERROR.value,
                                    error_source=ErrorSource.EMBEDDED_CODE.value,
                                    http_code_at_source=0)

                # log statement
                logger.error(msg, extra = {
                    "event": EventName.USER_INPUT_VALIDATION.value,
                    "data": error_obj
                })

                raise StepExecutionError(msg, error_obj)    

            if type == "INT":
                try:
                    structure[name] = int(input.get("value"))
                except Exception as ex:
                    msg = "Cannot convert: '{}' into an integer".format(input.get("value"))

                    error_obj = create_step_error(message=msg,
                                        details=[str(ex)],
                                        error_type=ErrorType.USER_INPUT_ERROR.value,
                                        error_source=ErrorSource.EMBEDDED_CODE.value,
                                        http_code_at_source=0)

                    # log statement
                    logger.error(msg, extra = {
                        "event": EventName.USER_INPUT_VALIDATION.value,
                        "data": error_obj
                    })

                    raise StepExecutionError(str(ex), error_obj)                

            elif type == "FLOAT":
                try:
                    structure[name] = float(input.get("value"))
                except Exception as ex:
                    msg = "Cannot convert: '{}' into a float".format(input.get("value"))

                    error_obj = create_step_error(message=msg,
                                        details=[str(ex)],
                                        error_type=ErrorType.USER_INPUT_ERROR.value,
                                        error_source=ErrorSource.EMBEDDED_CODE.value,
                                        http_code_at_source=0)

                    # log statement
                    logger.error(msg, extra = {
                        "event": EventName.USER_INPUT_VALIDATION.value,
                        "data": error_obj
                    })

                    raise StepExecutionError(str(ex), error_obj)     

            elif type in ("STRING", "FLIGHT_COMMAND", "SIM_COMMAND", "FLIGHT_EVR", "SIM_EVR", "FLIGHT_TELEM", "SIM_TELEM", "VERIFICATION_COND", "FILE", "IMAGE", "SERIES"):
                structure[name] = input.get("value")

            elif type == "BOOL":
                if input.get("value") in ["true", "false"]:
                    structure[name] = input.get("value")
                else:
                    msg = "Boolean type value must either be 'true' or 'false'"

                    error_obj = create_step_error(message=msg,
                                        details=[msg],
                                        error_type=ErrorType.USER_INPUT_ERROR.value,
                                        error_source=ErrorSource.EMBEDDED_CODE.value,
                                        http_code_at_source=0)

                    # log statement
                    logger.error(msg, extra = {
                        "event": EventName.USER_INPUT_VALIDATION.value,
                        "data": error_obj
                    })

                    raise StepExecutionError(msg, error_obj)     

            
            elif type == "DATA_PATH":
                # get session id information from data path
                try:
                    session = get_session_information(input.get("value"))
                except Exception as ex:
                    msg = 'Failed to get session info for data_path: {}'.format(input.get("value"))

                    error_obj = create_step_error(message=msg,
                                        details=[str(ex)],
                                        error_type=ErrorType.USER_INPUT_ERROR.value,
                                        error_source=ErrorSource.EMBEDDED_CODE.value,
                                        http_code_at_source=0)

                    # log statement
                    logger.error(msg, extra = {
                        "event": EventName.DATA_PATH_CHECK.value,
                        "data": error_obj
                    })

                    raise StepExecutionError(str(ex), error_obj)     
                
                structure[name] = session

            elif type == "ENUM":
                
                input_value = input.get("value")

                enum_found = False

                for enumeration in input.get("enumerations"):
                    if enumeration.get("symbol") == input_value:
                        enum_found = True
                        structure[name] = enumeration.get("symbol")
                        break

                if enum_found is False:
                    msg = "An enum value for '{}' was not found".format(input.get("value"))

                    error_obj = create_step_error(message=msg,
                                        details=[],
                                        error_type=ErrorType.USER_INPUT_ERROR.value,
                                        error_source=ErrorSource.EMBEDDED_CODE.value,
                                        http_code_at_source=0)

                    # log statement
                    logger.error(msg, extra = {
                        "event": EventName.USER_INPUT_VALIDATION.value,
                        "data": error_obj
                    })

                    raise StepExecutionError(msg, error_obj)                   

            elif type == "TIME":
                try:
                    time_value = parse_to_doy(input.get("value"))
                    logger.info("Time value: {}".format(time_value))
                    structure[name] = time_value
                except StepExecutionError:
                    raise
                except Exception as ex:
                    msg = "There was an error retrieving a time value for time type: {}".format(input.get("value"))
                    
                    error_obj = create_step_error(message=msg,
                                        details=[str(ex)],
                                        error_type=ErrorType.USER_INPUT_ERROR.value,
                                        error_source=ErrorSource.EMBEDDED_CODE.value,
                                        http_code_at_source=0)

                    # log statement
                    logger.error(msg, extra = {
                        "event": EventName.USER_INPUT_VALIDATION.value,
                        "data": error_obj
                    })

                    raise StepExecutionError(str(ex), error_obj)     

        return structure

    def parse_output_types(self, outputs):
        structure = OrderedDict()
        
        # outputs and output arrays don't have a value, set to empty strings for all output entries
        for output in outputs:
            structure[output.get("name")] = ""

        return structure

    def parse_entry_type(self, entries):
        _entries = []

        for entry in entries:
            _entry = OrderedDict()
            _entry["verification_status"] = entry.get('verification_status', 'PENDING')
            _entry["entry_inputs"] = self.parse_input_types(inputs=entry["entry_inputs"])
            _entry["entry_outputs"] = self.parse_output_types(outputs=entry["entry_outputs"])
            _entry["entry_output_array"] = []
            _entries.append(_entry)
        
        return _entries        

'''
parse a string value as an integer such as "1", "2.0", "3.", etc
raise an exception if the value is not an integer
'''
def parse_int(value):
    if float(value) == (float(value) // 1):
        return int(float(value))
    else:
        raise Exception(f'{value} is not an integer')

