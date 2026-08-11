"""Unit tests for ``verification_lib`` CHANGE verification (``verify_change``).

Exercised through the public verifier subclasses with ``verify_on == "CHANGE"``
across MANUAL_INPUT, ENVIRONMENT_MANUAL, VERIFY_EHA and BUS_1553 step types.
"""

import pytest

from ingenium_embedded.verification_lib import VerifyInteger, VerifyFloat, VerifyString
from ingenium_embedded import ingenium_config as ic
from ingenium_embedded.ingenium_library import StepExecutionError, register_session


def _q(**over):
    q = {
        "verification_condition": "EQUAL",
        "verification_values": ["5"],
        "verify_on": "CHANGE",
        "actual_value": 10,
        "type": "INTEGER",
    }
    q.update(over)
    return q


class TestManualInputChange:
    def test_integer_change(self):
        ic.manual_input_variables["v1"] = {"actual_value": 5, "type": "INTEGER"}
        q = _q(name="v1", verification_values=["5"], actual_value=10)
        status = VerifyInteger({"step_type": "MANUAL_INPUT"}, q).verify()[2]
        assert status == "PASS"  # change = 10 - 5 = 5

    def test_float_change(self):
        ic.manual_input_variables["v1"] = {"actual_value": 1.5, "type": "FLOAT"}
        q = _q(name="v1", type="FLOAT", verification_values=["0.5"], actual_value=2.0)
        status = VerifyFloat({"step_type": "MANUAL_INPUT"}, q).verify()[2]
        assert status == "PASS"  # change = 2.0 - 1.5 = 0.5

    def test_record_condition_rejected_for_change(self):
        ic.manual_input_variables["v1"] = {"actual_value": 5, "type": "INTEGER"}
        q = _q(name="v1", verification_condition="RECORD", verification_values=[])
        with pytest.raises(StepExecutionError):
            VerifyInteger({"step_type": "MANUAL_INPUT"}, q).verify()

    def test_name_not_found(self):
        q = _q(name="missing", verification_values=["5"], actual_value=10)
        with pytest.raises(StepExecutionError):
            VerifyInteger({"step_type": "MANUAL_INPUT"}, q).verify()

    def test_type_mismatch(self):
        ic.manual_input_variables["v1"] = {"actual_value": "x", "type": "STRING"}
        q = _q(name="v1", type="INTEGER", verification_values=["5"], actual_value=10)
        with pytest.raises(StepExecutionError):
            VerifyInteger({"step_type": "MANUAL_INPUT"}, q).verify()

    def test_integer_conversion_error(self):
        ic.manual_input_variables["v1"] = {"actual_value": "notint", "type": "INTEGER"}
        q = _q(name="v1", verification_values=["5"], actual_value=10)
        with pytest.raises(StepExecutionError):
            VerifyInteger({"step_type": "MANUAL_INPUT"}, q).verify()


class TestEnvironmentChange:
    def test_environment_float_change(self):
        ic.environment_step_variables["temperature"] = {"actual_value": 20.0}
        q = _q(type="FLOAT", verification_values=["5"], actual_value=25.0)
        ver = VerifyFloat({"step_type": "ENVIRONMENT_MANUAL"}, q, environment_type="temperature")
        assert ver.verify()[2] == "PASS"  # change = 25 - 20 = 5

    def test_environment_not_found(self):
        q = _q(type="FLOAT", verification_values=["5"], actual_value=25.0)
        ver = VerifyFloat({"step_type": "ENVIRONMENT_MANUAL"}, q, environment_type="humidity")
        with pytest.raises(StepExecutionError):
            ver.verify()


class TestEhaChange:
    def test_eha_integer_change(self):
        register_session("SIDE A", 7)
        ic.channel_variables["7:C-1"] = {"actual_value": 3}
        q = _q(data_path="SIDE A", channel_id="C-1", verification_values=["7"])
        eha = {"actual_value": 10, "verification_status": ""}
        ver = VerifyInteger({"step_type": "VERIFY_EHA"}, q, eha_response=eha)
        assert ver.verify()[2] == "PASS"  # change = 10 - 3 = 7

    def test_eha_recorded_not_found(self):
        register_session("SIDE A", 7)
        q = _q(data_path="SIDE A", channel_id="MISSING", verification_values=["7"])
        eha = {"actual_value": 10, "verification_status": ""}
        ver = VerifyInteger({"step_type": "VERIFY_EHA"}, q, eha_response=eha)
        with pytest.raises(StepExecutionError):
            ver.verify()

    def test_eha_string_change_rejected(self):
        register_session("SIDE A", 7)
        ic.channel_variables["7:C-1"] = {"actual_value": "x"}
        q = _q(data_path="SIDE A", channel_id="C-1", verification_condition="EQUAL",
               verification_values=["a"], actual_value="b")
        eha = {"actual_value": "b", "verification_status": ""}
        ver = VerifyString({"step_type": "VERIFY_EHA"}, q, eha_response=eha)
        with pytest.raises(StepExecutionError):
            ver.verify()


class TestBus1553Change:
    def test_bus_integer_change(self):
        ic.mil_1553_variables["busvar"] = {"actual_value": 2}
        q = _q(bus_1553_var="busvar", verification_values=["8"], actual_value=10)
        eha = {"actual_value": 10, "verification_status": ""}
        ver = VerifyInteger({"step_type": "BUS_1553"}, q, eha_response=eha)
        assert ver.verify()[2] == "PASS"  # change = 10 - 2 = 8

    def test_bus_recorded_not_found(self):
        q = _q(bus_1553_var="missing", verification_values=["8"], actual_value=10)
        eha = {"actual_value": 10, "verification_status": ""}
        ver = VerifyInteger({"step_type": "BUS_1553"}, q, eha_response=eha)
        with pytest.raises(StepExecutionError):
            ver.verify()
