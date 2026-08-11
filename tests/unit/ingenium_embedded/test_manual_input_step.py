"""Unit tests for ``ingenium_embedded.manual_input_step``.

The ``Verify`` collaborator is mocked so verification logic is exercised via its
public contract without hitting a venue.
"""

import pytest

from ingenium_embedded import manual_input_step as step_mod
from ingenium_embedded import ingenium_config as ic
from ingenium_embedded.ingenium_library import StepExecutionError, create_step_error

from mocks.test_helpers import make_step


def _fake_verify(status="PASS", exc=None):
    class _FakeVerify:
        def __init__(self, step, entry, **kw):
            self.entry = entry

        @classmethod
        def factory(cls, step, entry, **kw):
            return cls(step, entry, **kw)

        def verify(self):
            if exc is not None:
                raise exc
            self.entry["verification_status"] = status
            return ("input_response", self.entry.get("actual_value"), status)

    return _FakeVerify


def _step(entries):
    return make_step("MANUAL_INPUT", {"entries": entries})


class TestCastActualValue:
    def test_integer_ok(self):
        entry = {"type": "INTEGER", "actual_value": "42"}
        assert step_mod.cast_actual_value(entry)["actual_value"] == 42

    def test_integer_bad_raises(self):
        with pytest.raises(StepExecutionError):
            step_mod.cast_actual_value({"type": "INTEGER", "actual_value": "x"})

    def test_float_ok(self):
        entry = {"type": "FLOAT", "actual_value": "4.5"}
        assert step_mod.cast_actual_value(entry)["actual_value"] == 4.5

    def test_float_bad_raises(self):
        with pytest.raises(StepExecutionError):
            step_mod.cast_actual_value({"type": "FLOAT", "actual_value": "x"})

    def test_string_passthrough(self):
        entry = {"type": "STRING", "actual_value": "hello"}
        assert step_mod.cast_actual_value(entry)["actual_value"] == "hello"


class TestRecordResults:
    def test_records_into_config(self):
        step_mod.record_results({"name": "v1"}, {"foo": "bar"})
        assert ic.manual_input_variables["v1"] == {"foo": "bar"}


class TestManualInputRun:
    def test_success_pass(self, monkeypatch):
        monkeypatch.setattr(step_mod, "Verify", _fake_verify("PASS"))
        step = _step([{"name": "a", "type": "STRING", "actual_value": "x"}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"

    def test_fail_status(self, monkeypatch):
        monkeypatch.setattr(step_mod, "Verify", _fake_verify("FAIL"))
        step = _step([{"name": "a", "type": "STRING", "actual_value": "x"}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "FAIL"

    def test_cast_error_returns_error(self, monkeypatch):
        monkeypatch.setattr(step_mod, "Verify", _fake_verify("PASS"))
        step = _step([{"name": "a", "type": "INTEGER", "actual_value": "not-int"}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"]["error_type"] == "USER_INPUT_ERROR"

    def test_verify_step_execution_error(self, monkeypatch):
        err = create_step_error(message="v boom")
        monkeypatch.setattr(step_mod, "Verify", _fake_verify(exc=StepExecutionError("v", err)))
        step = _step([{"name": "a", "type": "STRING", "actual_value": "x"}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"] == err

    def test_error_mode_raises(self):
        step = _step([{"name": "_TEST_MODE_", "type": "STRING", "actual_value": "RUN_ERROR"}])
        with pytest.raises(ZeroDivisionError):
            step_mod.run(step)
