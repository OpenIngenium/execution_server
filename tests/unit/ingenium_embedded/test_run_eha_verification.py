"""Unit tests for ``verification_lib.run_eha_verification`` (the EHA orchestrator
behind verify_eha_step / wait_eha_step).

All venue collaborators are mocked and the query window is forced to be already
expired so the polling loop runs exactly once.
"""

from datetime import datetime

import pytest

from ingenium_embedded import verification_lib as vlib
from ingenium_embedded import ingenium_library as ing_lib
from ingenium_embedded.ingenium_library import StepExecutionError, create_step_error

from mocks.test_helpers import make_step


def _fake_verify(status="PASS"):
    class _V:
        @classmethod
        def factory(cls, step, entry, value_type=None, eha_response=None):
            return cls()

        def verify(self):
            return ({}, 5, status)

    return _V


@pytest.fixture(autouse=True)
def patch_collaborators(monkeypatch):
    monkeypatch.setattr(ing_lib, "validate_times", lambda si, st: ("t1", "t2", "s", "e"))
    # Force the query window to have already elapsed -> single loop iteration.
    monkeypatch.setattr(ing_lib, "convert_time", lambda e: datetime(2000, 1, 1))
    monkeypatch.setattr(ing_lib, "refresh_venue_tokens", lambda *a, **k: None)
    monkeypatch.setattr(ing_lib, "report_step_results", lambda *a, **k: None)
    monkeypatch.setattr(ing_lib, "determine_actual_value", lambda entry, eha: (eha, "INTEGER"))
    monkeypatch.setattr(ing_lib, "record_channel_data", lambda *a, **k: None)
    monkeypatch.setattr(vlib.time, "sleep", lambda s: None)


def _entry(**over):
    e = {"channel_id": "C", "data_path": "SIDE A", "verification_condition": "EQUAL",
         "verification_values": [5], "verify_on": "VALUE", "type": "INTEGER"}
    e.update(over)
    return e


def _step(entries):
    return make_step("VERIFY_EHA", {"entries": entries})


class TestRunEhaVerification:
    def test_empty_entries_errors(self):
        result = vlib.run_eha_verification(_step([]), wait=False)
        assert result["execution"]["meta_data"]["status"] == "ERROR"

    def test_validate_times_error(self, monkeypatch):
        err = create_step_error(message="t")
        monkeypatch.setattr(ing_lib, "validate_times", lambda si, st: (_ for _ in ()).throw(StepExecutionError("t", err)))
        result = vlib.run_eha_verification(_step([_entry()]), wait=False)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"] == err

    def test_missing_data_path(self):
        result = vlib.run_eha_verification(_step([_entry(data_path=None)]), wait=False)
        assert result["execution"]["meta_data"]["status"] == "ERROR"

    def test_missing_channel_id(self):
        result = vlib.run_eha_verification(_step([_entry(channel_id=None)]), wait=False)
        assert result["execution"]["meta_data"]["status"] == "ERROR"

    def test_query_step_execution_error(self, monkeypatch):
        err = create_step_error(message="q")
        monkeypatch.setattr(ing_lib, "RealtimeEHAs", lambda **k: (_ for _ in ()).throw(StepExecutionError("q", err)))
        result = vlib.run_eha_verification(_step([_entry()]), wait=False)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"] == err

    def test_query_generic_error(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "RealtimeEHAs", lambda **k: (_ for _ in ()).throw(ValueError("x")))
        result = vlib.run_eha_verification(_step([_entry()]), wait=False)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"]["error_type"] == "QUERY_ERROR"

    def test_success_pass(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "RealtimeEHAs", lambda **k: [{"channelId": "C", "ert": "t"}])
        monkeypatch.setattr(vlib, "Verify", _fake_verify("PASS"))
        result = vlib.run_eha_verification(_step([_entry()]), wait=False)
        assert result["execution"]["meta_data"]["status"] == "PASS"

    def test_fail_status(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "RealtimeEHAs", lambda **k: [{"channelId": "C", "ert": "t"}])
        monkeypatch.setattr(vlib, "Verify", _fake_verify("FAIL"))
        result = vlib.run_eha_verification(_step([_entry()]), wait=False)
        assert result["execution"]["meta_data"]["status"] == "FAIL"

    def test_not_present_no_telemetry_passes(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "RealtimeEHAs", lambda **k: [])
        result = vlib.run_eha_verification(_step([_entry(verification_condition="NOT_PRESENT")]), wait=False)
        assert result["execution"]["meta_data"]["status"] == "PASS"

    def test_pending_no_telemetry_fails(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "RealtimeEHAs", lambda **k: [])
        result = vlib.run_eha_verification(_step([_entry(verification_condition="EQUAL")]), wait=False)
        assert result["execution"]["meta_data"]["status"] == "FAIL"

    def test_verify_step_execution_error(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "RealtimeEHAs", lambda **k: [{"channelId": "C", "ert": "t"}])
        err = create_step_error(message="v")

        class _Boom:
            @classmethod
            def factory(cls, step, entry, value_type=None, eha_response=None):
                return cls()

            def verify(self):
                raise StepExecutionError("v", err)

        monkeypatch.setattr(vlib, "Verify", _Boom)
        result = vlib.run_eha_verification(_step([_entry()]), wait=False)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"] == err

    def test_wait_true_pass(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "RealtimeEHAs", lambda **k: [{"channelId": "C", "ert": "t"}])
        monkeypatch.setattr(vlib, "Verify", _fake_verify("PASS"))
        result = vlib.run_eha_verification(_step([_entry()]), wait=True)
        assert result["execution"]["meta_data"]["status"] == "PASS"
