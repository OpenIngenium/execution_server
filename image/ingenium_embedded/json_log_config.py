import logging
import json_logging
import json
import traceback
from datetime import datetime
from collections import OrderedDict
from . import ingenium_config as ic

json_logging.ENABLE_JSON_LOGGING = True

class CustomJSONLog(logging.Formatter):
    """
    Customized logger
    """
    python_log_prefix = 'python.'
    def get_exc_fields(self, record):
        if record.exc_info:
            return self.format_exception(record.exc_info)
        elif record.exc_text:
            return record.exc_text
        else:
            return ''

    @classmethod
    def format_exception(cls, exc_info):
        return ''.join(traceback.format_exception(*exc_info)) if exc_info else ''

    def format(self, record):
        json_log_object = OrderedDict()
        json_log_object['timestamp'] = datetime.utcnow().isoformat() + 'Z'
        json_log_object['level'] = record.levelname
        json_log_object['message'] = record.getMessage()
        json_log_object['service'] = "EMBEDDED_CODE"
        json_log_object['user_name'] = ic.username

        if hasattr(record, 'event'):
            json_log_object['event'] = record.event
        if hasattr(record, 'data'):
            json_log_object['data'] = record.data            

        if self.get_exc_fields(record):
            if 'data' not in json_log_object:
                json_log_object['data'] = OrderedDict()
                json_log_object['data']['details'] = [self.get_exc_fields(record)]
            else:
                details = json_log_object['data'].get('details', None)
                if details is None:
                    json_log_object['data']['details'] = [self.get_exc_fields(record)]
                elif isinstance(details, list):
                    details.append(self.get_exc_fields(record))
                else:
                    # keep the details 
                    pass

        return json.dumps(json_log_object)

def logger_init():
    json_logging.init_non_web(custom_formatter=CustomJSONLog)