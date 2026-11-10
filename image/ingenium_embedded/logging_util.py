import logging
from . import ingenium_config
from . import json_log_config as json_log
import sys


json_log.logger_init()
logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stderr))
# FORMAT = '[%(levelname)s] : [%(asctime)s.%(msecs)03dZ] %(message)s'
# logging.basicConfig(format=FORMAT, datefmt='%Y-%m-%dT%H:%M:%S')
logger.setLevel(ingenium_config.loglevel)

def set_level(level):
    """
    "level" input must be in uppercase and match a valid level for Python's standard logger
    "INFO", "DEBUG", "WARN", "ERROR", "CRITICAL"
    """
    logger.setLevel(level)
    print("Logger level set to: {}".format(level))

