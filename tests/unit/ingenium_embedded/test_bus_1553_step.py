"""Unit tests for ``ingenium_embedded.bus_1553_step``.

Covers the pure helpers (``convert_value``, ``calculate_next_start_time``) and
both the VERIFY and WAIT polling paths of ``run`` with every venue collaborator
mocked (query, verification, response aggregator, token refresh, reporting,
clock, sleep).
"""

import pytest

from ingenium_embedded import bus_1553_step as step_mod
from ingenium_embedded import ingenium_library as ing_lib
from ingenium_embedded import ingenium_config as ic
from ingenium_embedded.ingenium_library import StepExecutionError, create_step_error

from mocks.test_helpers import make_step


# ---------------------------------------------------------------------------
# convert_value
# ---------------------------------------------------------------------------
class TestConvertValue:
    def test_int(self):
        assert step_mod.convert_value("INT", "42") == (42, "INTEGER")

    def test_uint(self):
        assert step_mod.convert_value("UINT", "7") == (7, "INTEGER")

    def test_int_bad_raises(self):
        with pytest.raises(StepExecutionError):
            step_mod.convert_value("INT", "x")

    def test_float(self):
        assert step_mod.convert_value("FLOAT", "4.5") == (4.5, "FLOAT")

    def test_float_bad_raises(self):
        with pytest.raises(StepExecutionError):
            step_mod.convert_value("FLOAT", "x")

    @pytest.mark.parametrize("dt", ["HEX", "BIN", "ENUM"])
    def test_string_types(self, dt):
        assert step_mod.convert_value(dt, "0xFF") == ("0xFF", "STRING")

    def test_unknown_type_raises(self):
        with pytest.raises(StepExecutionError):
            step_mod.convert_value("WHAT", "1")


# ---------------------------------------------------------------------------
# calculate_next_start_time
# ---------------------------------------------------------------------------
class TestCalculateNextStartTime:
    def test_empty_returns_input(self):
        assert step_mod.calculate_next_start_time([], "START", "SCET") == "START"

    def test_scet(self):
        responses = [{"time_scet": "2020-100T00:00:00.123", "time_sclk": "1"}]
        assert step_mod.calculate_next_start_time(responses, "s", "SCET") == "2020-100T00:00:00"

    def test_scet_missing_raises(self):
        with pytest.raises(StepExecutionError):
            step_mod.calculate_next_start_time([{"time_scet": "", "time_sclk": "1"}], "s", "SCET")

    def test_sclk(self):
        responses = [{"time_sclk": "555", "time_scet": "x"}]
        assert step_mod.calculate_next_start_time(responses, "s", "SCLK") == "555"

    def test_sclk_missing_raises(self):
        with pytest.raises(StepExecutionError):
            step_mod.calculate_next_start_time([{"time_sclk": "", "time_scet": "x"}], "s", "SCLK")


# ---------------------------------------------------------------------------
# run() shared fakes
# ---------------------------------------------------------------------------
FUTURE_END = "2035-100T00:00:00"
TIMES = ("ts", "te", "2020-100T00:00:00", FUTURE_END)


class _FakeClock:
    def __init__(self, step=1.0):
        self.t = 0.0
        self.step = step

    def time(self):
        v = self.t
        self.t += self.step
        return v


def _fake_bus_response():
    class _F:
        def __init__(self, entries, *a):
            self.entries = [dict(e) for e in entries]
            self.payload = {"entries": self.entries}

        def return_intermediate_response(self):
            return self.payload

        def update_bus_entry(self, index, latest_response, bus_variable, verification_status, actual_value):
            self.entries[index]["verification_status"] = verification_status

        def update_entry_verification_status(self, index, status):
            self.entries[index]["verification_status"] = status

    return _F


def _fake_verify(status="PASS"):
    class _V:
        @classmethod
        def factory(cls, step, entry, **kw):
            return cls()

        def verify(self):
            return ({}, 1, status)

    return _V


BUS_ROW = {
    "data_value": "42", "converted_value": "", "data_type": "INT", "rti": 0,
    "bus_name": "B", "dictionary": "d", "log_file": "l",
    "time_sclk": "1", "time_scet": "2020-100T00:00:00.0",
}


@pytest.fixture(autouse=True)
def patch_common(monkeypatch):
    monkeypatch.setattr(step_mod, "validate_times", lambda results, step_type: TIMES)
    monkeypatch.setattr(step_mod, "refresh_venue_tokens", lambda *a, **k: None)
    monkeypatch.setattr(step_mod, "report_step_results", lambda *a, **k: None)
    monkeypatch.setattr(step_mod, "record_bus_1553_data", lambda *a, **k: None)
    monkeypatch.setattr(step_mod, "Bus1553Response", _fake_bus_response())
    monkeypatch.setattr(step_mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(step_mod.time, "time", _FakeClock().time)


def _step(entries, verify_wait="VERIFY", time_type="SCLK", timeout=100):
    return make_step("BUS_1553", {
        "verify_wait": verify_wait, "time_type": time_type, "timeout": timeout,
        "entries": entries,
    })


def _entry(**over):
    e = {"bus_1553_var": "v1", "raw_convert": "CONVERT", "verification_condition": "PRESENT"}
    e.update(over)
    return e


# ---------------------------------------------------------------------------
# run() — validation & error paths
# ---------------------------------------------------------------------------
class TestBus1553Validation:
    def test_missing_time_type(self):
        step = _step([_entry()], time_type=None)
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"]["error_type"] == "TIME_VALIDATION_ERROR"

    def test_validate_times_error(self, monkeypatch):
        err = create_step_error(message="t")
        monkeypatch.setattr(step_mod, "validate_times", lambda r, s: (_ for _ in ()).throw(StepExecutionError("t", err)))
        step = _step([_entry()])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"] == err

    def test_run_dummy(self):
        ic.manual_input_variables["step_function_name"] = {"actual_value": "run_dummy"}
        step = _step([_entry()])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"


# ---------------------------------------------------------------------------
# run() — VERIFY path
# ---------------------------------------------------------------------------
class TestBus1553Verify:
    def test_verify_pass(self, monkeypatch):
        monkeypatch.setattr(step_mod, "Verify", _fake_verify("PASS"))
        monkeypatch.setattr(ing_lib, "query_bus_1553", lambda **k: [dict(BUS_ROW)])
        step = _step([_entry()], verify_wait="VERIFY", timeout=100)
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"

    def test_verify_not_present_timeout_pass(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "query_bus_1553", lambda **k: [])
        step = _step([_entry(verification_condition="NOT_PRESENT")], verify_wait="VERIFY", timeout=1)
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"

    def test_verify_absent_timeout_fail(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "query_bus_1553", lambda **k: [])
        step = _step([_entry(verification_condition="PRESENT")], verify_wait="VERIFY", timeout=1)
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "FAIL"

    def test_verify_query_step_execution_error(self, monkeypatch):
        err = create_step_error(message="q")
        monkeypatch.setattr(ing_lib, "query_bus_1553", lambda **k: (_ for _ in ()).throw(StepExecutionError("q", err)))
        step = _step([_entry()], verify_wait="VERIFY")
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"] == err

    def test_verify_query_generic_error(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "query_bus_1553", lambda **k: (_ for _ in ()).throw(ValueError("x")))
        step = _step([_entry()], verify_wait="VERIFY")
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"]["error_type"] == "QUERY_ERROR"

    def test_verify_convert_value_error(self, monkeypatch):
        bad_row = dict(BUS_ROW, data_type="INT", converted_value="not-int")
        monkeypatch.setattr(ing_lib, "query_bus_1553", lambda **k: [bad_row])
        step = _step([_entry(raw_convert="CONVERT")], verify_wait="VERIFY")
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"]["error_type"] == "VALUE_CONVERSION_ERROR"


# ---------------------------------------------------------------------------
# run() — WAIT path
# ---------------------------------------------------------------------------
class TestBus1553Wait:
    def test_wait_pass(self, monkeypatch):
        monkeypatch.setattr(step_mod, "Verify", _fake_verify("PASS"))
        monkeypatch.setattr(ing_lib, "query_bus_1553", lambda **k: [dict(BUS_ROW)])
        step = _step([_entry(raw_convert="RAW")], verify_wait="WAIT", timeout=100)
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"

    def test_wait_no_response_fail(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "query_bus_1553", lambda **k: [])
        step = _step([_entry(verification_condition="PRESENT")], verify_wait="WAIT", timeout=1)
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "FAIL"

    def test_wait_not_present_pass(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "query_bus_1553", lambda **k: [])
        step = _step([_entry(verification_condition="NOT_PRESENT")], verify_wait="WAIT", timeout=1)
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"

    def test_wait_query_step_execution_error(self, monkeypatch):
        err = create_step_error(message="q")
        monkeypatch.setattr(ing_lib, "query_bus_1553", lambda **k: (_ for _ in ()).throw(StepExecutionError("q", err)))
        step = _step([_entry()], verify_wait="WAIT")
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"] == err
