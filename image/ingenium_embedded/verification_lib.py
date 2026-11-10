from . import ingenium_config as ic
from .ingenium_library import create_step_error, return_step_with_error, StepExecutionError
from .logging_util import logger
from . import ingenium_library as ing_lib
from datetime import datetime, timedelta
import time
import math
import json
import copy
import traceback
from collections import OrderedDict

# Mapping between conditions and allowed data types for each.
data_type_mapping = {
    "GREATER_THAN": ["INTEGER", "UNSIGNED_INT", "SIGNED_INT", "FLOAT", "INT", "UINT"],
    "GREATER_THAN_OR_EQUAL": ["INTEGER", "UNSIGNED_INT", "SIGNED_INT", "FLOAT", "INT", "UINT"],
    "LESS_THAN": ["INTEGER", "UNSIGNED_INT", "SIGNED_INT", "FLOAT","INT", "UINT"],
    "LESS_THAN_OR_EQUAL": ["INTEGER", "UNSIGNED_INT", "SIGNED_INT", "FLOAT","INT", "UINT"],
    "EQUAL": ["INTEGER", "UNSIGNED_INT", "SIGNED_INT", "FLOAT", "STRING", "BOOLEAN", "INT", "UINT", "HEX", "BIN"],
    "NOT_EQUAL": ["INTEGER", "UNSIGNED_INT", "SIGNED_INT", "FLOAT", "STRING", "BOOLEAN", "INT", "UINT", "HEX", "BIN"],
    "RECORD": ["INTEGER", "UNSIGNED_INT", "SIGNED_INT", "FLOAT", "STRING", "BOOLEAN", "INT", "UINT", "HEX", "BIN"],
    "NOT_PRESENT": ["INTEGER", "UNSIGNED_INT", "SIGNED_INT", "FLOAT", "STRING", "BOOLEAN", "INT", "UINT", "HEX", "BIN"],
    "CONTAINS": ["STRING", "HEX", "BIN"],
    "INCLUSIVE_RANGE": ["INTEGER", "UNSIGNED_INT", "SIGNED_INT", "FLOAT", "INT", "UINT"],
    "EXCLUSIVE_RANGE": ["INTEGER", "UNSIGNED_INT", "SIGNED_INT", "FLOAT","INT", "UINT"]
}


# Factory class
class Verify(object):

    def factory(step, query, value_type=None, eha_response=None, environment_type=None):

        # Manual Input / Environment Manual steps have an explicit verification type in the user input. This verification type is used to route to the proper sub class.
        if step["step_type"] == "MANUAL_INPUT":

            # Need to provide a value type for integer, because there's three types of integers tbat can be procssed in this Verify class. INTEGEER, UNSIGNED_INT, SIGNED_INT
            if value_type == "INTEGER": return VerifyInteger(step, query)
            if value_type == "FLOAT": return VerifyFloat(step, query)
            if value_type == "STRING": return VerifyString(step, query)
            if value_type == "BOOLEAN": return VerifyBoolean(step, query)
            else:
                msg = "Unknown data type: {}".format(step["step_type"])

                # log statement
                logger.error(msg, extra = {
                    "event": ing_lib.EventName.USER_INPUT_VALIDATION.value,
                    "data": {
                        "message": msg,
                        "error_type": ing_lib.ErrorType.USER_INPUT_ERROR.value,
                        "error_source": ing_lib.ErrorSource.EMBEDDED_CODE.value,
                        "http_code_at_source": 0
                    }
                })

                error_obj = create_step_error(message=msg,
                                details=[],
                                error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                                error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                                http_code_at_source=0)
                raise StepExecutionError(msg, error_obj)

        # Verify and Wait EHA steps get their type from the realtime EHA response (channel type). This channel type is used to route to the proper verification sub class.
        # eha_response is passed to the class
        elif step["step_type"] in ["VERIFY_EHA", "WAIT_EHA", "BUS_1553"]:
            if value_type == "INTEGER": return VerifyInteger(step, query, eha_response=eha_response)
            if value_type == "FLOAT": return VerifyFloat(step, query, eha_response=eha_response)
            if value_type == "STRING": return VerifyString(step, query, eha_response=eha_response)
            else:
                msg = "Unknown data type: {}".format(value_type)

                error_obj = create_step_error(message=msg,
                                details=[],
                                error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                                error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                                http_code_at_source=0)

                # log statement
                logger.error(msg, extra = {
                    "event": ing_lib.EventName.USER_INPUT_VALIDATION.value,
                    "data": error_obj
                })

                raise StepExecutionError(msg, error_obj)
            
        # Environment step only allows for float type.
        # envrionment type (temperature, humidity) is passed to the class to make sure the appropriate type is used. (This is necessary for "CHANGE")
        elif step["step_type"] == "ENVIRONMENT_MANUAL":

            return VerifyFloat(step, query, environment_type=environment_type)

        else:
            msg = "Unknown step type: {}".format(step["step_type"])

            # log statement
            logger.error(msg, extra = {
                "event": ing_lib.EventName.USER_INPUT_VALIDATION.value,
                "data": {
                    "message": msg,
                    "error_type": ing_lib.ErrorType.USER_INPUT_ERROR.value,
                    "error_source": ing_lib.ErrorSource.EMBEDDED_CODE.value,
                    "http_code_at_source": 0
                }
            })

            error_obj = create_step_error(message=msg,
                            details=[],
                            error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                            error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)
            raise StepExecutionError(msg, error_obj)

    factory = staticmethod(factory)

# Base Class
class VerificationBase(object):

    def __init__(self, step, query, value_type, eha_response=None, environment_type=None):
        self.step = step
        self.query = query
        self.value_type = value_type
        self.eha_response = eha_response
        self.environment_type = environment_type
        self.condition = self.query["verification_condition"]
        self.verification_values = self.query["verification_values"]
        self.step_type = self.step["step_type"]
        self.verify_on = self.query["verify_on"]

    def type_check(self):

        if self.eha_response is not None:
            actual_value = self.eha_response["actual_value"]
        else:
            actual_value = self.query.get("actual_value")

        if self.step_type == "MANUAL_INPUT":
            verification_type = self.query["type"]

        # If a verification condition does not match type, raise error
        if data_type_mapping.get(self.condition) is not None:
            if self.value_type not in data_type_mapping[self.condition]:
                msg =  "{} not supported by data type '{}' ".format(self.condition, self.value_type)
               
                # log statement
                logger.error(msg, extra = {
                    "event": ing_lib.EventName.USER_INPUT_VALIDATION.value,
                    "data": {
                        "message": msg,
                        "error_type": ing_lib.ErrorType.USER_INPUT_ERROR.value,
                        "error_source": ing_lib.ErrorSource.EMBEDDED_CODE.value,
                        "http_code_at_source": 0
                    }
                })

                error_obj = create_step_error(message=msg,
                                details=[],
                                error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                                error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                                http_code_at_source=0)
                raise StepExecutionError(msg, error_obj)
        else:
            msg = "Condition: {} not found".format(self.condition)
           
            # log statement
            logger.error(msg, extra = {
                "event": ing_lib.EventName.USER_INPUT_VALIDATION.value,
                "data": {
                    "message": msg,
                    "error_type": ing_lib.ErrorType.USER_INPUT_ERROR.value,
                    "error_source": ing_lib.ErrorSource.EMBEDDED_CODE.value,
                    "http_code_at_source": 0
                }
            })

            error_obj = create_step_error(message=msg,
                            details=[],
                            error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                            error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)
            raise StepExecutionError(msg, error_obj)


        # if actual value is None, besides record and not_present, raise error
        if self.condition not in ["RECORD", "NOT_PRESENT"] and actual_value is None:
            msg="Condition: {} requires an actual value".format(actual_value)

            # log statement
            logger.error(msg, extra = {
                "event": ing_lib.EventName.USER_INPUT_VALIDATION.value,
                "data": {
                    "message": msg,
                    "error_type": ing_lib.ErrorType.USER_INPUT_ERROR.value,
                    "error_source": ing_lib.ErrorSource.EMBEDDED_CODE.value,
                    "http_code_at_source": 0
                }
            })

            error_obj = create_step_error(message=msg,
                            details=[],
                            error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                            error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)
            raise StepExecutionError(msg, error_obj)


        # mathematical operators require verification values length of 1, anything else will raise error
        if self.condition in ["GREATER_THAN", "LESS_THAN", "GREATER_THAN_OR_EQUAL", "LESS_THAN_OR_EQUAL", "EQUAL", "NOT_EQUAL", "CONTAINS"] and len(self.verification_values) != 1:
            
            if len(self.verification_values) == 0:
                msg = "Can not evaluate verification condition '{}' with an empty verify value.".format(self.condition)
            else:
                msg = "Condition: '{}' can only have 1 verification value.".format(self.condition)

            # log statement
            logger.error(msg, extra = {
                "event": ing_lib.EventName.USER_INPUT_VALIDATION.value,
                "data": {
                    "message": msg,
                    "error_type": ing_lib.ErrorType.USER_INPUT_ERROR.value,
                    "error_source": ing_lib.ErrorSource.EMBEDDED_CODE.value,
                    "http_code_at_source": 0
                }
            })

            error_obj = create_step_error(message=msg,
                            details=[],
                            error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                            error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)
            raise StepExecutionError(msg, error_obj)

        # range operators require verification values length of 2, anything else will raise error
        if self.condition in ["INCLUSIVE_RANGE", "EXCLUSIVE_RANGE"]:
            if len(self.verification_values) > 2:
                msg = "Condition: '{}' cannot have more than 2 values".format(self.condition)

                # log statement
                logger.error(msg, extra = {
                    "event": ing_lib.EventName.USER_INPUT_VALIDATION.value,
                    "data": {
                        "message": msg,
                        "error_type": ing_lib.ErrorType.USER_INPUT_ERROR.value,
                        "error_source": ing_lib.ErrorSource.EMBEDDED_CODE.value,
                        "http_code_at_source": 0
                    }
                })

                error_obj = create_step_error(message=msg,
                                details=[],
                                error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                                error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                                http_code_at_source=0)
                raise StepExecutionError(msg, error_obj)


            elif len(self.verification_values) < 2:
                msg = "Condition: '{}' cannot have less than 2 values".format(self.condition)

                # log statement
                logger.error(msg, extra = {
                    "event": ing_lib.EventName.USER_INPUT_VALIDATION.value,
                    "data": {
                        "message": msg,
                        "error_type": ing_lib.ErrorType.USER_INPUT_ERROR.value,
                        "error_source": ing_lib.ErrorSource.EMBEDDED_CODE.value,
                        "http_code_at_source": 0
                    }
                })

                error_obj = create_step_error(message=msg,
                                details=[],
                                error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                                error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                                http_code_at_source=0)
                raise StepExecutionError(msg, error_obj)

        # if step type is manual input or environment and the condition is not present, raise error
        if self.step_type in ["MANUAL_INPUT", "ENVIRONMENT_MANUAL"] and self.condition == "NOT_PRESENT":
            msg = "Step type: '{}' cannot use the 'NOT_PRESENT' condition".format(self.step_type)

            # log statement
            logger.error(msg, extra = {
                "event": ing_lib.EventName.USER_INPUT_VALIDATION.value,
                "data": {
                    "message": msg,
                    "error_type": ing_lib.ErrorType.USER_INPUT_ERROR.value,
                    "error_source": ing_lib.ErrorSource.EMBEDDED_CODE.value,
                    "http_code_at_source": 0
                }
            })

            error_obj = create_step_error(message=msg,
                            details=[],
                            error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                            error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)
            raise StepExecutionError(msg, error_obj)


        return True

    def verify_change(self):

        # actual value is taken from the user input for manual input/env. steps. Else it is taken from the realtime EHA response for Wait / Verify EHA
        if self.eha_response is not None:
            actual_value = self.eha_response["actual_value"]
        else:
            actual_value = self.query.get("actual_value")

        if self.step_type == "MANUAL_INPUT":
            name = self.query["name"]

        # Record, not present, contains cannot use CHANGE
        if self.condition in ["RECORD", "NOT_PRESENT", "CONTAINS"]:
            msg = "Condition: {} does not support self.condition 'CHANGE'".format(self.condition)

            # log statement
            logger.error(msg, extra = {
                "event": ing_lib.EventName.USER_INPUT_VALIDATION.value,
                "data": {
                    "message": msg,
                    "error_type": ing_lib.ErrorType.USER_INPUT_ERROR.value,
                    "error_source": ing_lib.ErrorSource.EMBEDDED_CODE.value,
                    "http_code_at_source": 0
                }
            })

            error_obj = create_step_error(message=msg,
                            details=[],
                            error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                            error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)
            raise StepExecutionError(msg, error_obj)

        # Verify / Wait EHA steps use channeltype as a sort of explicit data type.
        if self.step_type in ["VERIFY_EHA", "WAIT_EHA", "BUS_1553"]:
            if self.step_type in ["VERIFY_EHA", "WAIT_EHA"]:
                data_path = self.query.get("data_path")
                channel_id = self.query.get("channel_id")
                try:
                    session = ing_lib.get_session_information(data_path)
                    channel_key = f'{session}:{channel_id}'
                    recorded_value = ic.channel_variables[channel_key]["actual_value"]
                except Exception as ex:
                    msg = f"Previous record was not found. data_path: {data_path} channel_id: {channel_id} details: {str(ex)}"
                    
                    # log statement
                    logger.error(msg, extra = {
                        "event": ing_lib.EventName.CHECK_RECORDED_VALUE.value,
                        "data": {
                            "message": msg,
                            "error_type": ing_lib.ErrorType.USER_INPUT_ERROR.value,
                            "error_source": ing_lib.ErrorSource.EMBEDDED_CODE.value,
                            "http_code_at_source": 0
                        }
                    })

                    error_obj = create_step_error(message=msg,
                                    details=[],
                                    error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                                    error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                                    http_code_at_source=0)
                    raise StepExecutionError(msg, error_obj)  
            # if step_type == "BUS_1553"
            else:

                bus_var_name = self.query["bus_1553_var"]

                try:
                    recorded_value = ic.mil_1553_variables[bus_var_name]["actual_value"]
                except:

                    msg = "Previous record for 1553 bus var name: {} - was not found".format(bus_var_name)
                    
                    # log statement
                    logger.error(msg, extra = {
                        "event": ing_lib.EventName.CHECK_RECORDED_VALUE.value,
                        "data": {
                            "message": msg,
                            "error_type": ing_lib.ErrorType.USER_INPUT_ERROR.value,
                            "error_source": ing_lib.ErrorSource.EMBEDDED_CODE.value,
                            "http_code_at_source": 0
                        }
                    })

                    error_obj = create_step_error(message=msg,
                                    details=[],
                                    error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                                    error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                                    http_code_at_source=0)
                    raise StepExecutionError(msg, error_obj)                      

            if self.value_type == "INTEGER":
                try:
                    change = int(actual_value) - int(recorded_value)
                except:
                    msg = "Could not turn recorded/actual value into an integer."

                    # log statement
                    logger.error(msg, extra = {
                        "event": ing_lib.EventName.CHECK_RECORDED_VALUE.value,
                        "data": {
                            "message": msg,
                            "error_type": ing_lib.ErrorType.USER_INPUT_ERROR.value,
                            "error_source": ing_lib.ErrorSource.EMBEDDED_CODE.value,
                            "http_code_at_source": 0
                        }
                    })

                    error_obj = create_step_error(message=msg,
                                    details=[],
                                    error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                                    error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                                    http_code_at_source=0)
                    raise StepExecutionError(msg, error_obj)

            elif self.value_type == "FLOAT":
                try:
                    change = float(actual_value) - float(recorded_value)
                except:
                    msg = "Could not turn recorded/actual value into a float."
                    
                    # log statement
                    logger.error(msg, extra = {
                        "event": ing_lib.EventName.CHECK_RECORDED_VALUE.value,
                        "data": {
                            "message": msg,
                            "error_type": ing_lib.ErrorType.USER_INPUT_ERROR.value,
                            "error_source": ing_lib.ErrorSource.EMBEDDED_CODE.value,
                            "http_code_at_source": 0
                        }
                    })

                    error_obj = create_step_error(message=msg,
                                    details=[],
                                    error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                                    error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                                    http_code_at_source=0)
                    raise StepExecutionError(msg, error_obj)
            
            elif self.value_type == "STRING":
                msg = "'Verify On' - 'Change' does not support channel type: {}".format(self.value_type)

                error_obj = create_step_error(message=msg,
                                details=[],
                                error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                                error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                                http_code_at_source=0)

                # log statement
                logger.error(msg, extra = {
                    "event": ing_lib.EventName.CHECK_RECORDED_VALUE.value,
                    "data": error_obj
                })

                raise StepExecutionError(msg, error_obj)               


        if self.step_type == "ENVIRONMENT_MANUAL":
            try:
                recorded_value = ic.environment_step_variables[self.environment_type]["actual_value"]
                change = actual_value - recorded_value
            except:
                msg = "Environment step variable was not found"

                # log statement
                logger.error(msg, extra = {
                    "event": ing_lib.EventName.CHECK_RECORDED_VALUE.value,
                    "data": {
                        "message": msg,
                        "error_type": ing_lib.ErrorType.USER_INPUT_ERROR.value,
                        "error_source": ing_lib.ErrorSource.EMBEDDED_CODE.value,
                        "http_code_at_source": 0
                    }
                })

                error_obj = create_step_error(message=msg,
                                details=[],
                                error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                                error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                                http_code_at_source=0)
                raise StepExecutionError(msg, error_obj)

        if self.step_type == "MANUAL_INPUT":

            try:
                recorded_value = ic.manual_input_variables[name]["actual_value"]
            except:
                msg = "Manual input: {} was not found".format(name)

                # log statement
                logger.error(msg, extra = {
                    "event": ing_lib.EventName.CHECK_RECORDED_VALUE.value,
                    "data": {
                        "message": msg,
                        "error_type": ing_lib.ErrorType.USER_INPUT_ERROR.value,
                        "error_source": ing_lib.ErrorSource.EMBEDDED_CODE.value,
                        "http_code_at_source": 0
                    }
                })

                error_obj = create_step_error(message=msg,
                                details=[],
                                error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                                error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                                http_code_at_source=0)
                raise StepExecutionError(msg, error_obj)


            if self.query["type"] == "INTEGER" and ic.manual_input_variables[name]["type"] == "INTEGER":

                try:
                    recorded_value = int(recorded_value)
                    actual_value = int(actual_value)
                    change = actual_value - recorded_value
                except:
                    msg = "Could not turn recorded and/or actual value into an integer."
                    
                    # log statement
                    logger.error(msg, extra = {
                        "event": ing_lib.EventName.CHECK_RECORDED_VALUE.value,
                        "data": {
                            "message": msg,
                            "error_type": ing_lib.ErrorType.USER_INPUT_ERROR.value,
                            "error_source": ing_lib.ErrorSource.EMBEDDED_CODE.value,
                            "http_code_at_source": 0
                        }
                    })

                    error_obj = create_step_error(message=msg,
                                    details=[],
                                    error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                                    error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                                    http_code_at_source=0)
                    raise StepExecutionError(msg, error_obj)


            elif self.query["type"] == "FLOAT" and ic.manual_input_variables[name]["type"] == "FLOAT":

                try:
                    recorded_value = float(recorded_value)
                    actual_value = float(actual_value)
                    change = actual_value - recorded_value
                except:
                    msg = "Could not turn recorded and/or actual value into a float."
                    
                    # log statement
                    logger.error(msg, extra = {
                        "event": ing_lib.EventName.CHECK_RECORDED_VALUE.value,
                        "data": {
                            "message": msg,
                            "error_type": ing_lib.ErrorType.USER_INPUT_ERROR.value,
                            "error_source": ing_lib.ErrorSource.EMBEDDED_CODE.value,
                            "http_code_at_source": 0
                        }
                    })

                    error_obj = create_step_error(message=msg,
                                    details=[],
                                    error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                                    error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                                    http_code_at_source=0)
                    raise StepExecutionError(msg, error_obj)

            elif self.query["type"] in ["STRING", "BOOLEAN"] and ic.manual_input_variables[name]["type"] in ["STRING", "BOOLEAN"]:
                change = recorded_value

            else:
                msg = "Recorded value and verification types do not match. Recorded value type: '{}', Query value type: '{}'".format(self.query["type"], ic.manual_input_variables[name]["type"])
                
                # log statement
                logger.error(msg, extra = {
                    "event": ing_lib.EventName.CHECK_RECORDED_VALUE.value,
                    "data": {
                        "message": msg,
                        "error_type": ing_lib.ErrorType.USER_INPUT_ERROR.value,
                        "error_source": ing_lib.ErrorSource.EMBEDDED_CODE.value,
                        "http_code_at_source": 0
                    }
                })

                error_obj = create_step_error(message=msg,
                                details=[],
                                error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                                error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                                http_code_at_source=0)

                raise StepExecutionError(msg, error_obj)

        msg = f'CHANGE verification result. recorded_value: {recorded_value} actual_value: {actual_value} change: {change}'
        logger.info(msg)
        return change


# String validation
class VerifyString(VerificationBase):

    def __init__(self, step, query, eha_response=None):
        VerificationBase.__init__(self, step, query, value_type="STRING", eha_response=eha_response)

    def verify(self):

        actual_value = None

        try:
            base_verification = super(VerifyString, self).type_check()
        except StepExecutionError as ex:
            raise

        if self.eha_response is not None:
            if self.verify_on == "CHANGE":
                try:
                    actual_value = super(VerifyString, self).verify_change()
                except StepExecutionError:
                    raise
            else:
                actual_value = self.eha_response["actual_value"]
            # for Wait / Verify EHA, need to make sure that the realtime eha response is used.
            self.query = self.eha_response
        else:
            if self.verify_on == "CHANGE":
                try:
                    actual_value = super(VerifyString, self).verify_change()
                except StepExecutionError:
                    raise
            else:
                actual_value = self.query.get("actual_value")


        if self.condition == "EQUAL":
            for value in self.verification_values:

                if actual_value == value:
                    self.query["verification_status"] = "PASS"
                else:
                    self.query["verification_status"] = "FAIL"

        if self.condition == "NOT_EQUAL":
            for value in self.verification_values:

                if actual_value == value:
                    self.query["verification_status"] = "FAIL"
                else:
                    self.query["verification_status"] = "PASS"

        if self.condition == "RECORD":

            if actual_value is not None:
                self.query["verification_status"] = "PASS"
            else:
                self.query["verification_status"] = "FAIL"

        # not present
        if self.condition == "NOT_PRESENT":
            if actual_value is not None:
                self.query["verification_status"] = "FAIL"
            else:
                self.query["verification_status"] = "PASS"

        # contains
        if self.condition == "CONTAINS":

            for value in self.verification_values:
                if value in actual_value:
                    self.query["verification_status"] = "PASS"
                    break
                else:
                    self.query["verification_status"] = "FAIL"

        return self.query, actual_value, self.query["verification_status"]

# String validation
class VerifyBoolean(VerificationBase):

    def __init__(self, step, query, eha_response=None):
        VerificationBase.__init__(self, step, query, value_type="BOOLEAN", eha_response=eha_response)

        values_list = []

        try:
            for value in self.verification_values:
                values_list.append(value)

        except:
            msg = "Cannot convert verification values into boolean: {}".format(self.verification_values)
            
            # log statement
            logger.error(msg, extra = {
                "event": ing_lib.EventName.USER_INPUT_VALIDATION.value,
                "data": {
                    "message": msg,
                    "error_type": ing_lib.ErrorType.USER_INPUT_ERROR.value,
                    "error_source": ing_lib.ErrorSource.EMBEDDED_CODE.value,
                    "http_code_at_source": 0
                }
            })
            error_obj = create_step_error(message=msg,
                            details=[],
                            error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                            error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)

            raise StepExecutionError(msg, error_obj)

        self.verification_values = values_list

    def verify(self):

        actual_value = None

        try:
            base_verification = super(VerifyBoolean, self).type_check()
        except StepExecutionError:
            raise


        # determine actual value. There are a few scenarios to consider.
        if self.eha_response is not None:
            if self.verify_on == "CHANGE":
                try:
                    change = super(VerifyBoolean, self).verify_change()
                except StepExecutionError:
                    raise
                actual_value = change
            else:
                actual_value = self.eha_response["actual_value"]
            # for Wait / Verify EHA, need to make sure that the realtime eha response is used.
            self.query = self.eha_response
        else:
            if self.verify_on == "CHANGE":
                try:
                    change = super(VerifyBoolean, self).verify_change()
                    actual_value = change
                except StepExecutionError:
                    raise
            else:
                if self.query["actual_value"] is not None:
                    actual_value = self.query["actual_value"]
                else:
                    actual_value = self.query["actual_value"]

        if self.condition == "EQUAL":
            for value in self.verification_values:
                if actual_value == value:
                    self.query["verification_status"] = "PASS"
                else:
                    self.query["verification_status"] = "FAIL"

        if self.condition == "NOT_EQUAL":
            for value in self.verification_values:

                if actual_value == value:
                    self.query["verification_status"] = "FAIL"
                else:
                    self.query["verification_status"] = "PASS"

        if self.condition == "RECORD":

            if actual_value is not None:
                self.query["verification_status"] = "PASS"
            else:
                self.query["verification_status"] = "FAIL"

        # not present
        if self.condition == "NOT_PRESENT":

            if actual_value is not None:
                self.query["verification_status"] = "FAIL"
            else:
                self.query["verification_status"] = "PASS"

        return self.query, actual_value, self.query["verification_status"]


# Integer Validation
class VerifyInteger(VerificationBase):

    def __init__(self, step, query, eha_response=None):
        VerificationBase.__init__(self, step, query, value_type="INTEGER", eha_response=eha_response)

        values_list = []

        # type cast appropriately
        for value in self.verification_values:
            if self.condition in ["RECORD", "NOT_PRESENT"]:
                continue
            try:
                value = ing_lib.parse_int(value)
            except:
                msg = "Verification values must be type integer."
                # log statement
                logger.error(msg, extra = {
                    "event": ing_lib.EventName.USER_INPUT_VALIDATION.value,
                    "data": {
                        "message": msg,
                        "error_type": ing_lib.ErrorType.USER_INPUT_ERROR.value,
                        "error_source": ing_lib.ErrorSource.EMBEDDED_CODE.value,
                        "http_code_at_source": 0
                    }
                })
                error_obj = create_step_error(message=msg,
                                details=[],
                                error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                                error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                                http_code_at_source=0)
                raise StepExecutionError(msg, error_obj)
            values_list.append(value)

        self.verification_values = values_list

    def verify(self):
        try:
            base_verification = super(VerifyInteger, self).type_check()
        except StepExecutionError:
            raise


        if self.eha_response is not None:
            if self.verify_on == "CHANGE":
                try:
                    actual_value = super(VerifyInteger, self).verify_change()
                except StepExecutionError:
                    raise
            else:
                actual_value = self.eha_response["actual_value"]

            # for Wait / Verify EHA, need to make sure that the realtime eha response is used.
            self.query = self.eha_response
        else:
            if self.verify_on == "CHANGE":
                try:
                    actual_value = super(VerifyInteger, self).verify_change()
                except StepExecutionError:
                    raise
            else:
                actual_value = self.query.get("actual_value")


        if self.condition == "GREATER_THAN":
            for value in self.verification_values:

                if actual_value > value:
                    self.query["verification_status"] = "PASS"
                else:
                    self.query["verification_status"] = "FAIL"

        # less than
        if self.condition == "LESS_THAN":
            for value in self.verification_values:

                if actual_value < value:
                    self.query["verification_status"] = "PASS"
                else:
                    self.query["verification_status"] = "FAIL"

        #gtoe
        if self.condition == "GREATER_THAN_OR_EQUAL":
            for value in self.verification_values:

                close = math.isclose(value, actual_value, rel_tol=1e-08)
                if close is True or actual_value >= value:
                    self.query["verification_status"] = "PASS"
                else:
                    self.query["verification_status"] = "FAIL"


        #ltoe
        if self.condition == "LESS_THAN_OR_EQUAL":
            for value in self.verification_values:

                close = math.isclose(value, actual_value, rel_tol=1e-08)
                if close is True or actual_value <= value:
                    self.query["verification_status"] = "PASS"
                else:
                    self.query["verification_status"] = "FAIL"


        if self.condition == "EQUAL":
            for value in self.verification_values:

                if actual_value == value:
                    self.query["verification_status"] = "PASS"
                else:
                    self.query["verification_status"] = "FAIL"


        if self.condition == "NOT_EQUAL":
            for value in self.verification_values:

                if actual_value == value:
                    self.query["verification_status"] = "FAIL"
                else:
                    self.query["verification_status"] = "PASS"


        if self.condition == "RECORD":

            if actual_value or actual_value == 0:
                self.query["verification_status"] = "PASS"
            else:
                self.query["verification_status"] = "FAIL"

        # not present
        if self.condition == "NOT_PRESENT":
            if actual_value is not None:
                self.query["verification_status"] = "FAIL"
            else:
                self.query["verification_status"] = "PASS"

        # inclusive range
        if self.condition == "INCLUSIVE_RANGE":

            if actual_value >= min(self.verification_values) and actual_value <= max(self.verification_values):
                self.query["verification_status"] = "PASS"
            else:
                self.query["verification_status"] = "FAIL"

        # exclusive range
        if self.condition == "EXCLUSIVE_RANGE":

            if actual_value > min(self.verification_values) and actual_value < max(self.verification_values):
                self.query["verification_status"] = "PASS"
            else:
                self.query["verification_status"] = "FAIL"

        return self.query, actual_value, self.query["verification_status"]


# Float Verification
class VerifyFloat(VerificationBase):

    def __init__(self, step, query, eha_response=None, environment_type=None):
        VerificationBase.__init__(self, step, query, value_type="FLOAT", eha_response=eha_response, environment_type=environment_type)
        values_list = []

        # type cast verification values to FLOAT

        for value in self.verification_values:

            if self.condition in ["RECORD", "NOT_PRESENT"]:
                continue
            
            try:
                value = float(value)
            except:
                msg = "Verification values must be type float."
                # log statement
                logger.error(msg, extra = {
                    "event": ing_lib.EventName.USER_INPUT_VALIDATION.value,
                    "data": {
                        "message": msg,
                        "error_type": ing_lib.ErrorType.USER_INPUT_ERROR.value,
                        "error_source": ing_lib.ErrorSource.EMBEDDED_CODE.value,
                        "http_code_at_source": 0
                    }
                })
                error_obj = create_step_error(message=msg,
                                details=[],
                                error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                                error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                                http_code_at_source=0)
                raise StepExecutionError(msg, error_obj)
            values_list.append(value)

        self.verification_values = values_list


    def verify(self):
        try:
            base_verification = super(VerifyFloat, self).type_check()
        except StepExecutionError:
            raise

        if self.eha_response is not None:
            if self.verify_on == "CHANGE":
                try:
                    actual_value = super(VerifyFloat, self).verify_change()
                except StepExecutionError:
                    raise
            else:
                actual_value = self.eha_response["actual_value"]
            # for Wait / Verify EHA, need to make sure that the realtime eha response is used.
            self.query = self.eha_response
        else:
            if self.verify_on == "CHANGE":
                try:
                    actual_value = super(VerifyFloat, self).verify_change()
                except StepExecutionError:
                    raise
            else:
                actual_value = self.query.get("actual_value")


        if self.condition == "GREATER_THAN":
            for value in self.verification_values:

                if actual_value > value:
                    self.query["verification_status"] = "PASS"
                else:
                    self.query["verification_status"] = "FAIL"


        # less than
        if self.condition == "LESS_THAN":
            for value in self.verification_values:

                if actual_value < value:
                    self.query["verification_status"] = "PASS"
                else:
                    self.query["verification_status"] = "FAIL"


        #gtoe
        if self.condition == "GREATER_THAN_OR_EQUAL":
            for value in self.verification_values:

                close = math.isclose(value, actual_value, rel_tol=1e-08)

                if close is True or actual_value >= value:
                    self.query["verification_status"] = "PASS"
                else:
                    self.query["verification_status"] = "FAIL"


        #ltoe
        if self.condition == "LESS_THAN_OR_EQUAL":
            for value in self.verification_values:

                close = math.isclose(value, actual_value, rel_tol=1e-08)

                if close is True or actual_value <= value:
                    self.query["verification_status"] = "PASS"
                else:
                    self.query["verification_status"] = "FAIL"


        if self.condition == "EQUAL":
            for value in self.verification_values:

                close = math.isclose(value, actual_value, rel_tol=1e-08)

                if close is True:
                    self.query["verification_status"] = "PASS"
                else:
                    self.query["verification_status"] = "FAIL"


        if self.condition == "NOT_EQUAL":
            for value in self.verification_values:

                close = math.isclose(value, actual_value, rel_tol=1e-08)

                if close is True:
                    self.query["verification_status"] = "FAIL"
                else:
                    self.query["verification_status"] = "PASS"


        if self.condition == "RECORD":
            if actual_value or actual_value == 0.0:
                self.query["verification_status"] = "PASS"
            else:
                self.query["verification_status"] = "FAIL"

        # not present
        if self.condition == "NOT_PRESENT":
            if actual_value is not None:
                self.query["verification_status"] = "FAIL"
            else:
                self.query["verification_status"] = "PASS"


        # inclusive range
        if self.condition == "INCLUSIVE_RANGE":

            max_close = math.isclose(max(self.verification_values), actual_value, rel_tol=1e-08)
            min_close = math.isclose(min(self.verification_values), actual_value, rel_tol=1e-08)

            if max_close is True or min_close is True:
                self.query["verification_status"] = "PASS"
            elif actual_value >= min(self.verification_values) and actual_value <= max(self.verification_values):
                self.query["verification_status"] = "PASS"
            else:
                self.query["verification_status"] = "FAIL"

        # exclusive range
        if self.condition == "EXCLUSIVE_RANGE":

            if actual_value > min(self.verification_values) and actual_value < max(self.verification_values):
                self.query["verification_status"] = "PASS"
            else:
                self.query["verification_status"] = "FAIL"

        return self.query, actual_value, self.query["verification_status"]


def verify_query_evr_results(evr_object):

    total_count = evr_object["total_count"]
    verification_value = evr_object["verification_value"]
    verification_condition = evr_object["verification_condition"]

    if verification_condition in ["GREATER_THAN", "LESS_THAN", "GREATER_THAN_OR_EQUAL", "LESS_THAN_OR_EQUAL"]:
        if type(verification_value) in [str, bool]:
            msg="Cannot use a string or boolean type"
            # log statement
            logger.error(msg, extra = {
                "event": ing_lib.EventName.USER_INPUT_VALIDATION.value,
                "data": {
                    "message": msg,
                    "error_type": ing_lib.ErrorType.USER_INPUT_ERROR.value,
                    "error_source": ing_lib.ErrorSource.EMBEDDED_CODE.value,
                    "http_code_at_source": 0
                }
            })
            evr_object["verification_status"] = "FAIL"
            return evr_object

    if verification_condition == "GREATER_THAN":
        if total_count > verification_value:
            evr_object["verification_status"] = "PASS"
        else:
            evr_object["verification_status"] = "FAIL"

    if verification_condition == "LESS_THAN":
        if total_count < verification_value:
            evr_object["verification_status"] = "PASS"
        else:
            evr_object["verification_status"] = "FAIL"

    if verification_condition == "GREATER_THAN_OR_EQUAL":
        if total_count >= verification_value:
            evr_object["verification_status"] = "PASS"
        else:
            evr_object["verification_status"] = "FAIL"

    if verification_condition == "LESS_THAN_OR_EQUAL":
        if total_count <= verification_value:
            evr_object["verification_status"] = "PASS"
        else:
            evr_object["verification_status"] = "FAIL"

    if verification_condition == "EQUAL":
        if total_count == verification_value:
            evr_object["verification_status"] = "PASS"
        else:
            evr_object["verification_status"] = "FAIL"

    if verification_condition == "NOT_EQUAL":
        if total_count != verification_value:
            evr_object["verification_status"] = "PASS"
        else:
            evr_object["verification_status"] = "FAIL"

    if verification_condition == "RECORD":
        if total_count != None:
            evr_object["verification_status"] = "PASS"
        else:
            evr_object["verification_status"] = "FAIL"


    return evr_object

def verify_data_product_condition(dp):


    if dp["verification_condition"] == "GREATER_THAN":
        if dp["total_count"] > dp["verification_value"]:
            dp["verification_status"] = "PASS"
        else:
            dp["verification_status"] = "FAIL"

    if dp["verification_condition"] == "LESS_THAN":
        if dp["total_count"] < dp["verification_value"]:
            dp["verification_status"] = "PASS"
        else:
            dp["verification_status"] = "FAIL"

    if dp["verification_condition"] == "GREATER_THAN_OR_EQUAL":
        if dp["total_count"] >= dp["verification_value"]:
            dp["verification_status"] = "PASS"
        else:
            dp["verification_status"] = "FAIL"

    if dp["verification_condition"] == "LESS_THAN_OR_EQUAL":
        if dp["total_count"] <= dp["verification_value"]:
            dp["verification_status"] = "PASS"
        else:
            dp["verification_status"] = "FAIL"

    if dp["verification_condition"] == "EQUAL":
        if dp["total_count"] == dp["verification_value"]:
            dp["verification_status"] = "PASS"
        else:
            dp["verification_status"] = "FAIL"

    if dp["verification_condition"] == "RECORD":
        if dp["total_count"]:
            dp["verification_status"] = "PASS"
        else:
            dp["verification_status"] = "FAIL"

    return dp



# Command verification base class
class CommandBase(object):

    def __init__(self, entry, data_path):
        self.data_path = data_path
        self.entry = entry
        # setting timeout
        if self.entry.get("timeout") is None:
            self.timeout = ic.cmd_timeout
        else:
            self.timeout = entry["timeout"]
        
        # placeholder values
        self.verification_start_time = datetime.utcnow()
        self.entry.update({
            'radiated': False,
            'radiated_time': '',
            'verified': False,
            'verified_time': ''
        })

    def get_remaining_seconds(self, slack_secs=0):
        '''
        return remaining seconds until timeout
        
        may return a negative number if timeout has passed
        '''
        current_time = datetime.utcnow()
        
        time_diff = current_time - self.verification_start_time
        
        remaining_secs = self.timeout - time_diff.total_seconds() + slack_secs
        
        logger.debug(f'verify_command remaining_secs: {remaining_secs}')
        
        return remaining_secs
        
    def verify_command(self):
        self.verification_start_time = datetime.utcnow()
        session = ing_lib.get_session_information(self.data_path)

        # Record EHA telemetry values
        start_time, end_time = ing_lib.get_telemetry_query_time(self.timeout)  
        
        for channel_id in self.channel_ids:
            if self.get_remaining_seconds() <= 0:
                return
                
            try:
                # push notice: looking for telemetry before sending command
                ehas = self.query_eha_telemetry(channel_id, start_time, end_time)
            except StepExecutionError as ex:
                msg = 'Failed to get initial value of channel_id: "{}"'.format(channel_id)
                error_obj = create_step_error(message=msg,
                                details=[str(ex)],
                                error_type=ing_lib.ErrorType.QUERY_ERROR.value,
                                error_source=ing_lib.ErrorSource.VENUE_SERVICE.value,
                                http_code_at_source=0)                
                logger.error(msg, extra = {
                    "event": ing_lib.EventName.QUERY_EHAS.value,
                    "data": error_obj
                })

                raise StepExecutionError(msg, error_obj)

            if len(ehas) == 0:
                msg = "No results were found for channel_id: '{}'".format(channel_id)
                error_obj = create_step_error(message=msg,
                                details=[],
                                error_type=ing_lib.ErrorType.QUERY_ERROR.value,
                                error_source=ing_lib.ErrorSource.VENUE_SERVICE.value,
                                http_code_at_source=0)                
                logger.error(msg, extra = {
                    "event": ing_lib.EventName.QUERY_EHAS.value,
                    "data": error_obj
                })

                raise StepExecutionError(msg, error_obj)
            else:
                channel_key = f'{session}:{channel_id}'
                # get the last value, which is the latest
                
                ic.cmd_variables[channel_key] = int(ehas[-1]["dn"])
                logger.debug(f'verify_command session: {session} channel_id: {channel_id} initial value: {ic.cmd_variables[channel_key]}')

        
        # send command
        if self.get_remaining_seconds() <= 0:
            return
        try:
            logger.debug(f'verify_command dispatch')
            cmd_dispatch = self.dispatch_cmd()
            logger.debug(f'verify_command dispatch is done: {cmd_dispatch}')
        except StepExecutionError as ex:
            msg = 'Command dispatch error'
            error_obj = create_step_error(message=msg,
                            details=[str(ex.error_obj)],
                            error_type=ing_lib.ErrorType.DISPATCH_ERROR.value,
                            error_source=ing_lib.ErrorSource.VENUE_SERVICE.value,
                            http_code_at_source=0)            
            logger.error(msg, extra = {
                "event": ing_lib.EventName.DISPATCH_COMMAND.value,
                "data": error_obj
            })

            raise StepExecutionError(msg, error_obj)


        # some error handling if command was dispatched with error
        if type(cmd_dispatch) == str:
            msg = "Command dispatch was unsuccessful."
            error_obj = create_step_error(message=msg,
                            details=[cmd_dispatch],
                            error_type=ing_lib.ErrorType.DISPATCH_ERROR.value,
                            error_source=ing_lib.ErrorSource.VENUE_SERVICE.value,
                            http_code_at_source=0)
                                        
            logger.error(msg, extra = {
                "event": ing_lib.EventName.DISPATCH_COMMAND.value,
                "data": error_obj
            })

            raise StepExecutionError(msg, error_obj)
        elif cmd_dispatch.get("message") is not None:
            msg = "Command dispatch was unsuccessful."
            # In this scenario a command was radiated but a dispatch was not returned.
            # radiated: GDS completed sending the command
            # dispatched: S/C received the command, validated, and initiated execution
            error_obj = create_step_error(message=msg,
                            details=[cmd_dispatch.get("message")],
                            error_type=ing_lib.ErrorType.DISPATCH_ERROR.value,
                            error_source=ing_lib.ErrorSource.VENUE_SERVICE.value,
                            http_code_at_source=0)
                                        
            logger.error(msg, extra = {
                "event": ing_lib.EventName.DISPATCH_COMMAND.value,
                "data": error_obj
            })

            raise StepExecutionError(msg, error_obj)
        else:
            self.entry['radiated'] = True if 'dispatchTime' in cmd_dispatch else False
            self.entry['radiated_time'] = cmd_dispatch['dispatchTime'] if 'dispatchTime' in cmd_dispatch else ''
        
        # send update
        step_execution = {
            'meta_data': {
                'status': 'RUNNING', 
                'status_message': 'Command radiated. (Timeout: {} secs).'.format(int(self.get_remaining_seconds()))
            },
            'results': self.step['execution']['results']
        }
        ing_lib.report_step_results(self.step, step_execution, None)
        
        if self.get_remaining_seconds() <= 0:
            return
            
        # Start from the command dispatch time, use the full timeout as the time window.
        # This would be searching beyond the timeout, but it does not hurt. The wide time window may be a bit more reliable.
        start_time, end_time = ing_lib.get_telemetry_query_time(self.timeout, time_input=cmd_dispatch["dispatchTime"])

        # STEP #A: Check EVR
        try:
            logger.debug(f'query_evr_telemetry start_time: {start_time} end_time: {end_time}')
            evrs = self.query_evr_telemetry(start_time, end_time)
            logger.debug('verify_command evrs:', extra={'data': evrs})
        except StepExecutionError as ex:
            msg = 'Failed to query EVR'
            error_obj = create_step_error(message=msg,
                            details=[str(ex)],
                            error_type=ing_lib.ErrorType.QUERY_ERROR.value,
                            error_source=ing_lib.ErrorSource.VENUE_SERVICE.value,
                            http_code_at_source=0)
                                        
            logger.error(msg, extra = {
                "event": ing_lib.EventName.QUERY_EHAS.value,
                "data": error_obj
            })

            raise StepExecutionError(msg, error_obj)

        # If no evr is found
        if len(evrs) == 0:
            return
        
        # verified time is based on the "ert" time from a successful evr
        else:
            # query_evr_telemetry uses chill_get_evr which returns the latest evr the last
            # use the latest EVR
            self.entry['verified_time'] = evrs[-1]['ert']

        # STEP 3B: Check telemetry to make sure that figures have increased by 1
        # Start from the command verify time, use the full timeout as the time window.
        # This would be searching beyond the timeout, but it does not hurt. The wide time window may be a bit more reliable.                           
        start_time, end_time = ing_lib.get_telemetry_query_time(self.timeout, time_input=self.entry['verified_time'])
                    
        if self.channel_ids:
            for channel_id in self.channel_ids:         
                # For each channel_id, keep checking if cmd verify channel has been changed until timeout                
                while True:
                    if self.get_remaining_seconds() <= 0:
                        return
                           
                    try:
                        ehas = self.query_eha_telemetry(channel_id, start_time, end_time)
                    except StepExecutionError as ex:
                        msg = 'Failed to get value of channel_id: "{}"'.format(channel_id)
                        error_obj = create_step_error(message=msg,
                                        details=[str(ex)],
                                        error_type=ing_lib.ErrorType.QUERY_ERROR.value,
                                        error_source=ing_lib.ErrorSource.VENUE_SERVICE.value,
                                        http_code_at_source=0)                        
                        logger.error(msg, extra = {
                            "event": ing_lib.EventName.QUERY_EHAS.value,
                            "data": error_obj
                        })

                        raise StepExecutionError(msg, error_obj)

                    if len(ehas) == 0:
                        self.entry['verified'] = False
                        self.entry['verified_time'] = ''
                    else:
                        logger.debug('verify_command channel_id current values', extra={'data': ehas})
                        # use the last one, which is the latest
                        eha = ehas[-1]
                        value_change = int(eha["dn"]) - int(ic.cmd_variables[channel_key])
                        logger.debug(f'verify_command session: {session} channel_id: {channel_id} current value: {eha["dn"]} value_change: {value_change}')

                        channel_key = f'{session}:{channel_id}'
                        if value_change == 0:
                            logger.debug('cmd verification channel has not changed. try again.')
                            time.sleep(1)
                        elif value_change == 1:
                            logger.debug('cmd verification channel incremented by one.')
                            self.entry['verified'] = True
                            ic.cmd_variables[channel_key] = int(eha["dn"])
                            break                   
                        else:
                            logger.warning('cmd verification channel incremented by more than one.')
                            self.entry['verified'] = False
                            self.entry['verified_time'] = ''
                            break
                # Break out of the loop. If any channel fails, verification fails.                            
                if not self.entry['verified']:
                    break
        else:
            # If no eha needs to be checked for verification, consider it verified.
            self.entry['verified'] = True

    def query_evr_telemetry(self, start_time, end_time):

        entry_start =datetime.utcnow()
        time_delta = 0
        query_counter = 0

        # while loop, while delta is less than timeout period keep looping
        logger.debug(f'while in query_evr_telemetry data_path: {self.data_path} evr_name: {self.evr_name} message: {self.message} verify_evr_msg: {ic.verify_evr_msg}')
        
        # If EVR messages contain command name (FSW or HW command) or file path (for command file step), we can use message filter.
        message = self.message if ic.verify_evr_msg else None

        while time_delta <= self.timeout:
            logger.debug(f'while in query_evr_telemetry start_time: {start_time} end_time: {end_time} time_delta: {time_delta} timeout: {self.timeout}')
            
            ing_lib.refresh_venue_tokens()

            query_counter += 1
            
            # make query for entry
            try:
                if (query_counter % ic.chill_query_frequency) > 0:
                    # Note that RealtimeEVR and venue server does not support evr_type input.
                    # The results will include both fsw and sse EVRs                       
                    evrs = ing_lib.RealtimeEVR(data_path=self.data_path,
                                            time_type='ERT',
                                            start_time=start_time,
                                            end_time=end_time,
                                            evr_name=self.evr_name,
                                            event_id=None,
                                            evr_level=None,
                                            message_filter=message,
                                            min_results=1,
                                            timeout=self.timeout)
                else:          
                    # try chill query periodically since GLAD may not hold data long enough
                    # evr_type is not specified. Chill query will default to fsw EVR.
                    evrs = ing_lib.ChillEVRQuery(data_path=self.data_path,
                                                time_type='ERT',
                                                start_time=start_time,
                                                end_time=end_time,
                                                evr_name=self.evr_name,
                                                evr_id=None,
                                                evr_type=None,
                                                evr_level=None,
                                                evr_module=None,
                                                message_filter=message,
                                                timeout=self.timeout)

                logger.debug(f'query_evr_telemetry evrs:', extra={'data': evrs})
                                           
            except Exception as ex:

                msg = "An EVR for {} was not found".format(self.message)
                logger.error(msg, extra = {
                    "event": ing_lib.EventName.QUERY_EVRS.value,
                    "data": {
                        "message": msg,
                        "error_type": ing_lib.ErrorType.QUERY_ERROR.value,
                        "error_source": ing_lib.ErrorSource.VENUE_SERVICE.value,
                        "http_code_at_source": 400,
                        "details": []
                    }
                })
                error_obj = create_step_error(message=msg,
                                details=[],
                                error_type=ing_lib.ErrorType.QUERY_ERROR.value,
                                error_source=ing_lib.ErrorSource.VENUE_SERVICE.value,
                                http_code_at_source=400)

                raise StepExecutionError(msg, error_obj)


            #  if query returns no results, it gives you a dictionary with key "message".
            if type(evrs) == list and len(evrs) > 0:
                return evrs

            else:
                time.sleep(1)
                entry_end = datetime.utcnow()
                time_delta = (entry_end - entry_start).total_seconds()


        return []


    def query_eha_telemetry(self, channel_id, start_time, end_time):
        # logger.debug(f'query_eha_telemetry channel_id: {channel_id} start_time: {start_time} end_time: {end_time}')

        entry_start = datetime.utcnow()
        time_delta = 0

        # while loop, while delta is less than timeout period keep looping
        while time_delta <= self.timeout:
            ing_lib.refresh_venue_tokens()
            ehas = ing_lib.RealtimeEHA(data_path=self.data_path,
                                       channel_id=channel_id,
                                       start_time=start_time,
                                       end_time=end_time,
                                       timeout=self.timeout)

            #  if query returns no results, it gives you a dictionary with key "message".
            if type(ehas) == list and len(ehas) > 0:
                return ehas

            else:
                time.sleep(2)
                entry_end = datetime.utcnow()
                time_delta = (entry_end - entry_start).total_seconds()


        return []


class FSWVerify(CommandBase):

    def __init__(self, entry, data_path, step):
        CommandBase.__init__(self, entry, data_path)

        self.command_type = entry["hw_fsw"]
        self.command_string = entry.get("cmd_string")
        self.string_selection = entry.get("string_selection", "DEFAULT")
        self.message = self.command_string.split(",")[0]
        self.channel_ids = ic.fsw_channels
        self.evr_name = ic.fsw_evr_name
        self.step = step

    def fsw_command_verification(self):
        super(FSWVerify, self).verify_command()

    def dispatch_cmd(self):
        return ing_lib.CommandFSW(data_path=self.data_path, command_string=self.command_string,
                                  string_selection=self.string_selection, validate=True,
                                  timeout=self.timeout)
class HWVerify(CommandBase):

    def __init__(self, entry, data_path, step):
        CommandBase.__init__(self, entry, data_path)

        self.command_type = entry["hw_fsw"]
        self.command_string = entry.get("cmd_string")
        self.string_selection = entry.get("string_selection", "DEFAULT")
        self.message = self.command_string
        self.channel_ids = ic.hw_channels
        self.evr_name = ic.hw_evr_name
        self.step = step

    def hw_command_verfication(self):
        super(HWVerify, self).verify_command()

    def dispatch_cmd(self):
        return ing_lib.CommandHW(data_path=self.data_path, command_stem=self.command_string, 
                                 string_selection=self.string_selection, timeout=self.timeout)

class BinaryFileVerify(CommandBase):

    def __init__(self, entry, data_path, step):
        CommandBase.__init__(self, entry, data_path)

        self.command_type = "BINARY_FILE"
        self.file_type = self.entry.get("file_type")
        self.file_path = self.entry.get("file_path")
        self.onboard_path = self.entry.get("onboard_path")
        self.overwrite = self.entry.get("overwrite")
        self.channel_ids = ic.binary_file_channels
        self.evr_name = ic.binary_file_evr_name
        self.message = self.onboard_path
        self.string_selection = self.entry.get("string_selection", "DEFAULT")
        self.step = step

    def binary_file_verification(self):

        super(BinaryFileVerify, self).verify_command()

    def dispatch_cmd(self):
        return ing_lib.CommandBinaryFile(data_path=self.data_path, source_file_path=self.file_path, target_file_path=self.onboard_path, 
                                         file_type=self.file_type, overwrite=self.overwrite, string_selection=self.string_selection, 
                                         timeout=self.timeout)


def run_eha_verification(step, wait=False):

    step_input = copy.deepcopy(step["execution_user_input"])
    timeout_input = ing_lib.get_dict_value(step_input, "timeout", ic.eha_rt_timeout)
    
    # Store channel values that will be used to record channel values at the end of step
    entry_record_map = {}

    # Check for empty entries
    if len(step_input['entries']) == 0:
        msg = 'No EHA channel information was provided'
        error_obj = create_step_error(message=msg,
                        details=[],
                        error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                        error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                        http_code_at_source=0)
        logger.error(msg, extra = {
            'event': ing_lib.EventName.USER_INPUT_VALIDATION.value,
            'data': error_obj
        })
        return return_step_with_error(step, error_obj)

    try:
        translated_start_time, translated_end_time, start_time, end_time = ing_lib.validate_times(step_input, step.get('step_type'))
    except StepExecutionError as ex:
        msg = "Time calculation error - {}.".format(json.dumps(ex.error_obj))

        error_obj = create_step_error(message=msg,
                        details=[],
                        error_type=ing_lib.ErrorType.TIME_VALIDATION_ERROR.value,
                        error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                        http_code_at_source=0)

        logger.error(msg, extra = {
            "event": ing_lib.EventName.TIME_VALIDATION.value,
            "data": error_obj
        })

        return return_step_with_error(step, ex.error_obj)

    # Python datetime object of query end time. Use a 10 seconds margin to account for any lag in AMPCS.
    end_time_obj_with_margin = ing_lib.convert_time(end_time) + timedelta(seconds=10.0)

    # initialize eha response object
    eha_response_object = ing_lib.EhaResponse(step_input['entries'], translated_start_time, translated_end_time, start_time, end_time)
    # initialize results so that input values are available when the step errors or is canceled.
    step['execution']['results'] = eha_response_object.return_intermediate_response()

    data_path_entry_map = OrderedDict()
    for index, entry in enumerate(step['execution']['results']['entries']):
        # collect data_path
        data_path = entry.get('data_path')
        if not data_path:
            msg = 'Data path was not provided'
            error_obj = create_step_error(message=msg,
                            details=[],
                            error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                            error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)

            logger.error(msg, extra = {
                "event": ing_lib.EventName.DATA_PATH_CHECK.value,
                "data": error_obj
            })
            return return_step_with_error(step, error_obj)
        
        # collect channel_id
        channel_id = entry.get('channel_id')
        if not channel_id:
            msg = 'EHA channel id was not provided'
            error_obj = create_step_error(message=msg,
                            details=[],
                            error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
                            error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
                            http_code_at_source=0)
            logger.error(msg, extra = {
                "event": ing_lib.EventName.USER_INPUT_VALIDATION.value,
                "data": error_obj
            })
            return return_step_with_error(step, error_obj)

        if data_path in data_path_entry_map:
            data_path_entries = data_path_entry_map[data_path]
            data_path_entries.append({'index': index, 'entry': entry})
        else:
            data_path_entries = [{'index': index, 'entry': entry}]
            data_path_entry_map[data_path] = data_path_entries

    run_once = False
    remaining_secs = max((end_time_obj_with_margin - datetime.utcnow()).total_seconds(), 0)
    entries_pending = True
    while (not run_once) or (remaining_secs > 0 and entries_pending):
        run_once = True
        ing_lib.refresh_venue_tokens()
        for data_path, data_path_entries in data_path_entry_map.items():
            channel_ids = list(map(lambda data_path_entry: data_path_entry['entry']['channel_id'], data_path_entries))
            try:
                msg = 'Searching for EHAs. data_path: {0} channel_ids: {1} start_time: {2} end_time: {3} remaining_secs: {4:.2f}'.format(data_path, 
                    channel_ids, start_time, end_time, remaining_secs)
                logger.debug(msg)
                intermediate_results = {
                    'meta_data': {
                        'status': 'RUNNING',
                        'status_message': msg
                    }
                }
                ing_lib.report_step_results(step, intermediate_results, None)

                ehas = ing_lib.RealtimeEHAs(data_path=data_path, channel_ids=channel_ids, 
                    start_time=start_time, end_time=end_time, timeout=timeout_input,
                    min_results=0)
            except StepExecutionError as ex:
                msg = "EHA query to venue failed"
                logger.error(msg, extra = {
                    "event": ing_lib.EventName.QUERY_EHAS.value,
                    "data": {
                        "message": msg,
                        "error_type": ing_lib.ErrorType.QUERY_ERROR.value,
                        "error_source": ing_lib.ErrorSource.VENUE_SERVICE.value,
                        "http_code_at_source": 400,
                        "details": [str(ex.error_obj)]
                    }
                })
                return return_step_with_error(step, ex.error_obj)
            except Exception as ex:
                msg = "EHA query to venue failed"
                error_obj = create_step_error(message=msg,
                                details=[traceback.format_exc()],
                                error_type=ing_lib.ErrorType.QUERY_ERROR.value,
                                error_source=ing_lib.ErrorSource.VENUE_SERVICE.value,
                                http_code_at_source=400)

                logger.error(msg, extra = {
                    "event": ing_lib.EventName.QUERY_EHAS.value,
                    "data": error_obj
                })

                return return_step_with_error(step, error_obj)
            
            eha_value_map = {}
            if type(ehas) == list:
                msg = 'EHA channels: {} Count: {}'.format(channel_ids, len(ehas))
                logger.info(msg, extra = {
                    'event': ing_lib.EventName.EHA_QUERY_RESPONSE.value
                })

                # Loop backward since latest ones are the last.
                for eha in reversed(ehas):
                    channel_id = eha.get('channelId')
                    if channel_id not in eha_value_map:
                        eha_value_map[channel_id] = eha
                
                for data_path_entry in data_path_entries:
                    index = data_path_entry['index']
                    entry = data_path_entry['entry']
                    data_path = entry.get('data_path')
                    channel_id = entry.get('channel_id')
                    verification_condition = entry.get('verification_condition')
                    eha = eha_value_map.get(channel_id, None)
                    if eha is None:
                        # Channel value was not available yet. Go to the next channel
                        # This will result in this behavior:
                        # - Whenever new channel values are available, they will be used to re-verify entries
                        # - If new channel values are not found, entry verification based on previous data will be kept
                        # - if wait == False
                        #     - When all entries are verified at least once (Every channel had at least one value), the step will complete.
                        # - if wait == True
                        #    - When all entries are verified at least once (Every channel had at least one value) and they PASSED, the step will complete.
                        continue

                    try:
                        updated_eha, value_type = ing_lib.determine_actual_value(entry, eha)
                        ver = Verify.factory(step, entry, value_type=value_type, eha_response=updated_eha)
                        returned_query, actual_value, verification_status = ver.verify()
                        # update eha response. this will update entry.
                        eha_response_object.update_eha_entry(index, eha, channel_id, verification_status, actual_value)
                    except StepExecutionError as ex:
                        return return_step_with_error(step, ex.error_obj)

                    '''
                    When verification_type == "CHANGE", the actual_value is different between "entry"
                    and "entry_copy". "entry" actual value contains the delta value which is presented to the user.
                    "entry_copy" contains the value returned from AMPCS which is stored as the
                    recorded value.
                    '''
                    entry_copy = copy.deepcopy(entry)
                    entry_copy.update(returned_query)
                    entry_record_map[channel_id] = entry_copy

            # check if all entries have been verified
            step_results = eha_response_object.return_intermediate_response()

            # if NOT_PRESENT failed, telemetry was found. The entry's verification is completed with FAIL.
            not_present_has_failed = False
            for entry in step_results['entries']:
                if entry['verification_condition'] == 'NOT_PRESENT' and entry['verification_status'] == 'FAIL':
                    not_present_has_failed = True
                    break

            if wait:
                entry_verifications = map(lambda entry: entry['verification_status'] != 'PASS', step_results['entries'])
            else:
                entry_verifications = map(lambda entry: entry['verification_status'] == 'PENDING', step_results['entries'])

            entries_pending = any(entry_verifications) and (not not_present_has_failed)

            # always update the remaining time
            remaining_secs = max((end_time_obj_with_margin - datetime.utcnow()).total_seconds(), 0)

            # report intermediate results
            msg = 'remaining_secs: {0:.2f}'.format(remaining_secs)
            intermediate_results = {
                'meta_data': {
                    'status': 'RUNNING', 
                    'status_message': msg
                },
                'results': step_results
            }
            ing_lib.report_step_results(step, intermediate_results, None)

            # sleep only when timeout has not happened
            if remaining_secs > 0 and entries_pending:
                time.sleep(1)

    # post processing of any PENDING entries
    for entry in step_results['entries']:
        # If verification_status is PENDING, that means no eha was found.
        channel_id = entry.get('channel_id')
        verification_condition = entry.get('verification_condition')
        if entry['verification_status'] == 'PENDING':
            if verification_condition == 'NOT_PRESENT':
                status_message = 'EHA telemetry not found until timeout. EHA channel: {} Passes NOT_PRESENT condition'.format(channel_id)
                verification_status = 'PASS'
            else:
                status_message = 'EHA telemetry not found until timeout. Fails {} condition'.format(verification_condition)
                verification_status = 'FAIL'

            # log it.  Note that log already happened when verification_status is not PENDING.
            logger.info(status_message, extra = {
                'event': ing_lib.EventName.VERIFY_EHAS.value
            })

            entry['verification_status'] = verification_status

    # record channel values just before completing step
    for channel_id in entry_record_map:
        ing_lib.record_channel_data(entry_record_map[channel_id])

    step_results = eha_response_object.return_intermediate_response()
    step['execution']['results'] = step_results

    for entry in step_results['entries']:
        if entry['verification_status'] == 'PASS':
            step['execution']['meta_data']['status'] = 'PASS'
        elif entry['verification_status'] == 'FAIL':
            step['execution']['meta_data']['status'] = 'FAIL'
            break

    step['execution']['meta_data']['status_message'] = ''

    return step


