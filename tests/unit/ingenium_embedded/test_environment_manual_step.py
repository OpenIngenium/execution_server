"""Unit tests for ``ingenium_embedded.environment_manual_step``."""

from ingenium_embedded import environment_manual_step as step_mod
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
            return ("resp", self.entry.get("actual_value"), status)

    return _FakeVerify


def _step(ui):
    return make_step("ENVIRONMENT_MANUAL", ui)


class TestEnvironmentManualStep:
    def test_temp_and_humidity_pass(self, monkeypatch):
        monkeypatch.setattr(step_mod, "Verify", _fake_verify("PASS"))
        step = _step({"temperature": {"actual_value": "20.5"}, "humidity": {"actual_value": "40"}})
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"
        assert ic.environment_step_variables["temperature"]["actual_value"] == 20.5
        assert ic.environment_step_variables["humidity"]["actual_value"] == 40.0

    def test_only_temperature_fails_step(self, monkeypatch):
        monkeypatch.setattr(step_mod, "Verify", _fake_verify("PASS"))
        step = _step({"temperature": {"actual_value": "20"}})
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "FAIL"

    def test_bad_temperature_value(self, monkeypatch):
        monkeypatch.setattr(step_mod, "Verify", _fake_verify("PASS"))
        step = _step({"temperature": {"actual_value": "hot"}})
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"]["error_type"] == "USER_INPUT_ERROR"

    def test_bad_humidity_value(self, monkeypatch):
        monkeypatch.setattr(step_mod, "Verify", _fake_verify("PASS"))
        step = _step({"temperature": {"actual_value": "20"}, "humidity": {"actual_value": "wet"}})
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"

    def test_temperature_verify_error(self, monkeypatch):
        err = create_step_error(message="boom")
        monkeypatch.setattr(step_mod, "Verify", _fake_verify(exc=StepExecutionError("b", err)))
        step = _step({"temperature": {"actual_value": "20"}})
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"] == err

    def test_humidity_verify_error(self, monkeypatch):
        err = create_step_error(message="boom-h")

        # Temperature passes, humidity raises.
        class _Mixed:
            def __init__(self, step, entry, **kw):
                self.entry = entry
                self.env = kw.get("environment_type")

            @classmethod
            def factory(cls, step, entry, **kw):
                return cls(step, entry, **kw)

            def verify(self):
                if self.env == "humidity":
                    raise StepExecutionError("b", err)
                self.entry["verification_status"] = "PASS"
                return ("r", None, "PASS")

        monkeypatch.setattr(step_mod, "Verify", _Mixed)
        step = _step({"temperature": {"actual_value": "20"}, "humidity": {"actual_value": "40"}})
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"] == err
