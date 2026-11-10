"""Unit tests for small manual/pass-through step modules."""

from ingenium_embedded import venue_config_manual_step
from ingenium_embedded import manual_input_step_with_sleep
from ingenium_embedded import ingenium_config as ic

from mocks.test_helpers import make_step


class TestVenueConfigManualStep:
    def test_passes_and_records_variable(self):
        step = make_step("VENUE_CONFIG_MANUAL", {"venue": "sit"})
        step["variable"] = {"name": "myvenue"}
        result = venue_config_manual_step.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"
        assert result["execution"]["results"] == {"venue": "sit"}
        assert ic.variables["myvenue"] == {"venue": "sit"}

    def test_passes_without_variable_name(self):
        step = make_step("VENUE_CONFIG_MANUAL", {"venue": "sit"})
        step["variable"] = {}
        result = venue_config_manual_step.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"


class TestManualInputStepWithSleep:
    def test_returns_inputs_after_sleeping(self, monkeypatch):
        sleeps = []
        monkeypatch.setattr(
            manual_input_step_with_sleep.time, "sleep", lambda s: sleeps.append(s)
        )
        step = make_step("MANUAL_INPUT_SLEEP", {"foo": "bar"})
        result = manual_input_step_with_sleep.run(step)
        assert result["execution"]["results"] == {"foo": "bar"}
        # Loops ten one-second sleeps; verify no real waiting occurred.
        assert sleeps == [1.0] * 10
