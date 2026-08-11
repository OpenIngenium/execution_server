"""Unit tests for ``ingenium_embedded.query_evr_step``.

``validate_times``, ``ing_lib.ChillEVRQuery`` and ``verify_query_evr_results``
are mocked so no venue query occurs.
"""

import pytest

from ingenium_embedded import query_evr_step as step_mod
from ingenium_embedded import ingenium_library as ing_lib
from ingenium_embedded import ingenium_config as ic
from ingenium_embedded.ingenium_library import StepExecutionError, create_step_error

from mocks.test_helpers import make_step


TIMES = ("2020-100T00:00:00", "2020-100T00:04:00", "2020-100T00:00:00", "2020-100T00:04:00")

RAW_EVR = {
    "evrName": "E", "sessionId": 1, "vcId": 0, "eventId": 2, "evrLevel": "INFO",
    "fromSSE": True, "evrMessage": "m", "evrModule": "M", "sclk": "1",
    "ert": "2020-100T00:00:01", "scet": "2020-100T00:00:01", "isRecorded": True,
}


@pytest.fixture(autouse=True)
def patch_times(monkeypatch):
    monkeypatch.setattr(step_mod, "validate_times", lambda results, step_type: TIMES)


def _step(data_path="SIDE A", **ui):
    base = {"data_path": data_path}
    base.update(ui)
    return make_step("QUERY_EVR", base)


class TestQueryEvrStep:
    def test_success_pass(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "ChillEVRQuery", lambda **k: [RAW_EVR])

        def fake_verify(results):
            results["verification_status"] = "PASS"

        monkeypatch.setattr(step_mod, "verify_query_evr_results", fake_verify)
        step = _step()
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"
        assert result["execution"]["results"]["total_count"] == 1

    def test_fail_status(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "ChillEVRQuery", lambda **k: [])
        monkeypatch.setattr(step_mod, "verify_query_evr_results", lambda r: r.update({"verification_status": "FAIL"}))
        step = _step()
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "FAIL"

    def test_missing_data_path(self):
        step = _step(data_path="")
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"]["error_type"] == "USER_INPUT_ERROR"

    def test_validate_times_error(self, monkeypatch):
        err = create_step_error(message="time boom")
        monkeypatch.setattr(step_mod, "validate_times", lambda r, s: (_ for _ in ()).throw(StepExecutionError("t", err)))
        step = _step()
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"] == err

    def test_query_step_execution_error(self, monkeypatch):
        err = create_step_error(message="q boom")
        monkeypatch.setattr(ing_lib, "ChillEVRQuery", lambda **k: (_ for _ in ()).throw(StepExecutionError("q", err)))
        step = _step()
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"] == err

    def test_query_generic_exception(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "ChillEVRQuery", lambda **k: (_ for _ in ()).throw(ValueError("x")))
        step = _step()
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"]["error_type"] == "QUERY_ERROR"

    def test_run_dummy(self):
        ic.manual_input_variables["step_function_name"] = {"actual_value": "run_dummy"}
        step = _step()
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"
        assert len(result["execution"]["results"]["evr_data"]) == 1
