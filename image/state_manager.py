import redis
import json
import logging

logger = logging.getLogger('Global')

class StateManager(object):
    HASH_TEMPLATE = 'execution_id:{}'

    def __init__(self, redis_host, redis_port):   
        self.redis_client = redis.StrictRedis(host=redis_host, port=redis_port)        

    def set_config_value(self, execution_id, key, value_str):
        hash = StateManager.HASH_TEMPLATE.format(execution_id)
        #logger.debug('set_config_value execution_id: {} key: {} value_str: {}'.format(execution_id, key, value_str)) 
    
        self.redis_client.hset(hash, key, value_str)  
   
    def get_config_value(self, execution_id, key):
        hash = StateManager.HASH_TEMPLATE.format(execution_id)
        value_str = self.redis_client.hget(hash, key) 
        value = None   
        if value_str is not None:
            value = value_str.decode('utf-8')
        
        # logger.debug('get_config_value execution_id: %s key: %s value:%s', 
        #    execution_id, key, value)   

        return value

    def get_variable_value(self, execution_id, var_name):
        hash = StateManager.HASH_TEMPLATE.format(execution_id)
        manual_input_variables_str = self.redis_client.hget(hash, 'manual_input_variables')    
        # logger.debug('manual_input_variables_str: %s', manual_input_variables_str)
        if manual_input_variables_str is None:
            return None
        else:
            manual_input_variables = json.loads(manual_input_variables_str.decode('utf-8'))
            return manual_input_variables.get(var_name)            

    def delete_execution(self, execution_id):
        hash = StateManager.HASH_TEMPLATE.format(execution_id)        
        self.redis_client.delete(hash)    