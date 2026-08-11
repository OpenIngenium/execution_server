"""Unit tests for ``ingenium_embedded.time_reference_step``."""

from ingenium_embedded import time_reference_step
from ingenium_embedded import ingenium_config as ic

from mocks.test_helpers import make_step


class TestTimeReferenceStep:
    def test_records_custom_time_reference(self, monkeypatch):
        monkeypatch.setattr(time_reference_step, "get_now_utc", lambda: "2020-01-01T00:00:00.000Z")
        step = make_step("TIME_REFERENCE_STEP", {"name": "MY_MARK"})
        result = time_reference_step.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"
        assert result["execution"]["results"]["time_value"] == "2020-01-01T00:00:00.000Z"
        assert ic.time_references["MY_MARK"] == "2020-01-01T00:00:00.000Z"

    def test_reserved_name_errors(self):
        step = make_step("TIME_REFERENCE_STEP", {"name": "LAST_STEP_START"})
        result = time_reference_step.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert (
            result["execution"]["meta_data"]["error"]["error_type"]
            == "USER_INPUT_ERROR"
        )
