"""Unit tests for ``ingenium_embedded.wait_evr_step``.

All venue collaborators (``validate_times``, ``EvrResponse``,
``refresh_venue_tokens``, ``ing_lib.RealtimeEVR``, reporting, sleeping) are
mocked so the polling loop runs deterministically in a single iteration.
"""

import pytest

from ingenium_embedded import wait_evr_step as step_mod
from ingenium_embedded import ingenium_library as ing_lib
from ingenium_embedded import ingenium_config as ic
from ingenium_embedded.ingenium_library import StepExecutionError, create_step_error

from mocks.test_helpers import make_step


# convert_time (used to detect passed query window) must parse end_time.
TIMES = ("2020-100T00:00:00", "2020-100T00:04:00", "2020-100T00:00:00", "2020-100T00:04:00")


def _fake_evr_response(status="PASS"):
    class _FakeEvrResponse:
        def __init__(self, entries, *a):
            self.entries = [dict(e) for e in entries]
            self.payload = {"entries": self.entries}

        def return_intermediate_response(self):
            return self.payload

        def update_evr_entry(self, index, evrs, total_count):
            self.entries[index]["verification_status"] = status

    return _FakeEvrResponse


@pytest.fixture(autouse=True)
def patch_collaborators(monkeypatch):
    monkeypatch.setattr(step_mod, "validate_times", lambda results, step_type: TIMES)
    monkeypatch.setattr(step_mod, "refresh_venue_tokens", lambda *a, **k: None)
    monkeypatch.setattr(step_mod, "report_step_results", lambda *a, **k: None)
    monkeypatch.setattr(step_mod.time, "sleep", lambda s: None)


def _entry(**over):
    e = {"evr_name": "E", "verification_condition": "EXISTS", "evr_type": "SSE"}
    e.update(over)
    return e


def _step(entries, data_path="SIDE A", timeout=0):
    return make_step("WAIT_EVR", {"data_path": data_path, "entries": entries, "timeout": timeout})


class TestWaitEvrStep:
    def test_success_pass(self, monkeypatch):
        monkeypatch.setattr(step_mod, "EvrResponse", _fake_evr_response("PASS"))
        monkeypatch.setattr(ing_lib, "RealtimeEVR", lambda **k: [{"fromSSE": True, "isRecorded": False}])
        step = _step([_entry()])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"

    def test_fail_status(self, monkeypatch):
        monkeypatch.setattr(step_mod, "EvrResponse", _fake_evr_response("FAIL"))
        monkeypatch.setattr(ing_lib, "RealtimeEVR", lambda **k: [])
        step = _step([_entry()], timeout=0)
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "FAIL"

    def test_missing_data_path(self, monkeypatch):
        monkeypatch.setattr(step_mod, "EvrResponse", _fake_evr_response())
        step = _step([_entry()], data_path="")
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"

    def test_validate_times_error(self, monkeypatch):
        err = create_step_error(message="t")
        monkeypatch.setattr(step_mod, "validate_times", lambda r, s: (_ for _ in ()).throw(StepExecutionError("t", err)))
        step = _step([_entry()])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"] == err

    def test_query_step_execution_error(self, monkeypatch):
        monkeypatch.setattr(step_mod, "EvrResponse", _fake_evr_response())
        err = create_step_error(message="q")
        monkeypatch.setattr(ing_lib, "RealtimeEVR", lambda **k: (_ for _ in ()).throw(StepExecutionError("q", err)))
        step = _step([_entry()])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"] == err

    def test_query_generic_exception(self, monkeypatch):
        monkeypatch.setattr(step_mod, "EvrResponse", _fake_evr_response())
        monkeypatch.setattr(ing_lib, "RealtimeEVR", lambda **k: (_ for _ in ()).throw(ValueError("x")))
        step = _step([_entry()])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"]["error_type"] == "QUERY_ERROR"

    def test_does_not_exist_fail_is_verified(self, monkeypatch):
        # DOES_NOT_EXIST + FAIL means the EVR was found -> step FAILs but the
        # loop treats the entry as "verified" (exercises that branch).
        monkeypatch.setattr(step_mod, "EvrResponse", _fake_evr_response("FAIL"))
        monkeypatch.setattr(ing_lib, "RealtimeEVR", lambda **k: [{"fromSSE": True}])
        step = _step([_entry(verification_condition="DOES_NOT_EXIST")])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "FAIL"

    def test_run_dummy(self):
        ic.manual_input_variables["step_function_name"] = {"actual_value": "run_dummy"}
        step = _step([_entry()])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"
