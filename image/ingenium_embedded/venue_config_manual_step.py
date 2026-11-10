from . import ingenium_config as ic
from .ingenium_library import ing_execution

@ing_execution
def run(step):
    results = step['execution_user_input']  
    
    # HK: does this need to set parameters in ingenium_config.py ?
    step['execution']['results'] = results 
    step['execution']['meta_data']['status'] = 'PASS'   
    
    variable_name = None
    if ('variable' in step) and ('name' in step['variable']):
        variable_name = step['variable']['name']

    if variable_name:
        variable_value = step['execution']['results']
        ic.variables[variable_name] = variable_value
            
    return step