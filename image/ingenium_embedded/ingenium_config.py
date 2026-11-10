#####################################################################################################################
#
# Ingenium_config.py
# Author: C.Swan/H.Kim/P.Chung
#
# This module is designed to be imported by Ingenium Steps, Ingenium Library functions, and execution functions.
# It holds the following types of information:
# - variables populated and managed by Ingenium EXEC - this includes things like variables, tokens, venue, etc
# - variables populated and managed by Ingenium step/library functions - this includes things like EHA last value
# - Defaults and constants used in either program
#
# For testing purposes the values in ingenium_config can be manipulated to simulate a testing or fault environment.
#
#####################################################################################################################

##################################################   Imports #######################################################
import os
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
########################################## Exec Managed Information ###############################################
username = ""
# Dictionary of user defined variables
variables = {}
environment_step_variables = {}
manual_input_variables = {}
channel_variables = {}
cmd_variables = {}
mil_1553_variables = {}

# The original JWT token. Execution service sets this automatically. Used to access venue config service.
ing_token=""
# The JWT token for venue service. Execution service sets this automatically. Used to access venue service.
venue_token=""

# running steps in synchronous or asynchronous mode
run_mode = 'SYNC'


# The PASS/FAIL status of the last executed step (expected "PASS" or "FAIL")
last_step_status = None

# constants to be used in Embedded code to mark the start and end time of the last step executed
standard_time_references = [
    'LAST_STEP_START',
    'LAST_STEP_END',
    'LAST_FSW_CMD_STEP_START',
    'LAST_FSW_CMD_STEP_END',
    'LAST_SSE_CMD_STEP_START',
    'LAST_SSE_CMD_STEP_END',
    'LAST_CMD_FILE_STEP_START',
    'LAST_CMD_FILE_STEP_END',
    'LAST_CMD_SCMF_FILE_STEP_START',
    'LAST_CMD_SCMF_FILE_STEP_END',
    'LAST_CUSTOM_SCRIPT_STEP_START',
    'LAST_CUSTOM_SCRIPT_STEP_END'
]

time_references = {}
for reference in standard_time_references:
    time_references[reference] = ''

# Venue and execution specific information
execution_id = None
venue_service_address=""
venue_sse=""
venue_name=""
venue_id=""
venue_type=None

# Note: ingenium_address is only used for embedded code tests and does not affect the functionalify of embedded code steps. 
# Ingenium address (of Ingenium swarm). This address is also used to get the list of venues in 'ingenium_step_sdk.py'.
# Use HTTP for now until we have all services behind HTTPS proxy.
ingenium_address=""
##########################################   Library/Step Managed Information #######################################



# This contains the mapping of a textual description
# Expected format: [{"data_path": "Side A", "session_id": "2322"},{"data_path": "Side B", "session_id": "2323"}]
ampcs_session_information =[]



##########################################   Ingenium Constants/Defaults   #############################################

# Default timeout when querying realtime queries
eha_rt_timeout=240 # seconds
evr_rt_timeout=240 # seconds
bus_1553_timeout=240 # seconds 
custom_script_timeout=240 #seconds

# Default timeouts when doing recorded (chill) queries
eha_chill_timeout=240 # seconds
evr_chill_timeout=240 # seconds
cmd_timeout=120 # seconds
mtak_timeout=120 # seconds
dp_timeout=240 # seconds

# Default look back or offset on start time
default_lookback=20 # seconds

# This is a timeout on the REST calls that is on top of the channel / etc query timeout
rest_timeout = 20

# perform chill query instead of GLAD query for every n trials
# this is used to get more robust query results given the limit of the buffer size of GLAD
chill_query_frequency = 10

# increasing interval in seconds. Ex: 1, 2, 4, 8, 16
query_trial_intervals = [pow(2,i) for i in range(5)]
max_query_trials = len(query_trial_intervals)

# REST header format
header = {'Authorization': '',
          'Content-Type': 'application/json',
          'Accept': 'application/json'}

# Whether or not to force SSL verification
ssl_verify = False

# Logging Level
loglevel="DEBUG"

# URL paths
venue_service_version = "v3"
venue_config_version = "v1"
core_service_version = "v5"
exec_server_version = "v4"

cmd_delay_seconds=1


# AWS-related configurations
media_bucket = os.environ.get("MEDIA_BUCKET", "")
file_server_api_host = os.environ.get("FILE_SERVER_API_HOST", "")


##########################################  COMMAND CONSTANTS   #############################################
def get_list_from_env_var(env_var_name, delimiter, default_list):
    '''
    get a list of string values from an environment variable
    
    Parameters
    --------
    env_var_name: string
        Name of the enviroment variable
    delimiter: String
        Delimiter used to separate values
    default_list: list
        List that will be returned if the environment variable is not defined
        
    Returns
    --------
    list
        values from the environment variable. 
        If the environment variable is not defined, default_list will be returned.
    
    '''
    env_var_value = os.environ.get(env_var_name, '')
    if env_var_value.strip() == '':
        return default_list
    else:
        # convert string to list
        return list(map(lambda value: value.strip(), env_var_value.split(delimiter)))

# Define EVR and EHA channels that indicate the dispatch of a command.
# If env variables are not defined, use a default value based on 
# the original configuration of Europa.
# Set env variable to an empty string to use an empty list for channel.

if os.getenv('VERIFY_FSW_CHANNELS') is None:
    fsw_channels = ['CMD-0027']
else:
    fsw_channels = get_list_from_env_var('VERIFY_FSW_CHANNELS', ':', [])
    
if os.getenv('VERIFY_FSW_EVR') is None:
    fsw_evr_name = 'CMD_SVC_EVR_VC1_CMD_DISPATCHED'
else:
    fsw_evr_name = os.getenv('VERIFY_FSW_EVR', '')

if os.getenv('VERIFY_HW_CHANNELS') is None:
    hw_channels = ['CMD-0024']
else:
    hw_channels = get_list_from_env_var('VERIFY_HW_CHANNELS', ':', [])
    
if os.getenv('VERIFY_HW_EVR') is None:
    hw_evr_name = 'CMD_SVC_EVR_VC0_COMMAND_DISPATCH'
else:
    hw_evr_name = os.getenv('VERIFY_HW_EVR', '')
    
if os.getenv('VERIFY_FILE_CHANNELS') is None:
    binary_file_channels = []
else:
    binary_file_channels = get_list_from_env_var('VERIFY_FILE_CHANNELS', ':', [])
    
if os.getenv('VERIFY_FILE_EVR') is None:
    binary_file_evr_name = 'FV_SVC_EVR_WRITE_NVFS_FILE_SUCCESS'
else:
    binary_file_evr_name = os.getenv('VERIFY_FILE_EVR', '')
    
if os.getenv('VERIFY_EVR_MSG') is None:
    verify_evr_msg = False
else:
    verify_evr_msg = os.getenv('VERIFY_EVR_MSG', 'false').lower() == 'true'
