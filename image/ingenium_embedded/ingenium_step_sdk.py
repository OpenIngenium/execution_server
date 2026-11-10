

import requests
import json
import getpass
import os
from . import ingenium_config as ic

#########################################  Test Config ################################################################

auth_endpoint_login=":8007/api/v2/login"
auth_endpoint_refresh=":8007/api/v2/refresh_token"
auth_endpoint_logout=":8007/api/v2/logout"
core_endpoint_venue=":8002/api/v5/venues"

def set_login_info(environment_variable=False):
    '''

    :return:
    '''
    global valid_user,valid_password
    if environment_variable:
        valid_user = os.environ['USERNAME']
        valid_password = os.environ['PASSWORD']
    else:
        valid_user=input("Enter Your User Name:")
        valid_password=getpass.getpass()

def login():
    '''
    Logs into Ingenium with username/password - updates token

    :return: None
    '''

    path = ic.ingenium_address + auth_endpoint_login
    user_name = valid_user
    pwd = valid_password
    logon = requests.get(path, auth=requests.auth.HTTPBasicAuth(user_name, pwd), verify=False)
    ic.ing_token=json.loads(logon.text)['access_token']
    ic.header['Authorization'] = "Bearer %s" % ic.ing_token

def refresh():
    '''
    Refreshes the existing token.

    :return: None
    '''

    path = ic.ingenium_address + auth_endpoint_refresh
    refresh = requests.post(path, headers=ic.header, verify=False)
    ic.ing_token = json.loads(refresh.text)['access_token']
    ic.header['Authorization'] = "Bearer %s" % ic.ing_token

def logout():
    '''
    Logs out of the application.

    :return:
    '''

    path = ic.ingenium_address + auth_endpoint_logout
    requests.post(path, headers=ic.header, verify=False)
    ic.ing_token = None
    ic.header['Authorization'] = None

def get_venues():
    '''
    Gets a list of venues

    :return:
    '''

    path = ic.ingenium_address + core_endpoint_venue
    venues=requests.get(path,headers=ic.header,verify=False)
    return json.loads(venues.text)
