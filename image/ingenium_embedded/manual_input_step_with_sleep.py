from .ingenium_library import ing_execution
import time

@ing_execution
def run(step):

    for i in range(10):
        time.sleep(1.0)
    
    inputs = step['execution_user_input']
    
    # HK: need to run verifications
    
    step['execution']['results'] = inputs 
    return step
