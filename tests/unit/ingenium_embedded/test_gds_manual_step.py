"""Unit tests for ``ingenium_embedded.gds_manual_step`` (MTAK restart step).

``ShutdownMTAK``, ``StartMTAK``, ``register_session`` and Core reporting are
mocked so no venue interaction occurs.
"""

import pytest

from ingenium_embedded import gds_manual_step as step_mod
from ingenium_embedded import ingenium_library as ing_lib
from ingenium_embedded import ingenium_config as ic
from ingenium_embedded.ingenium_library import StepExecutionError, create_step_error

from mocks.test_helpers import make_step


@pytest.fixture(autouse=True)
def patch_common(monkeypatch):
    monkeypatch.setattr(step_mod, "report_step_results", lambda *a, **k: None)
    monkeypatch.setattr(ing_lib, "ShutdownMTAK", lambda *a, **k: None)
    monkeypatch.setattr(ing_lib, "StartMTAK", lambda *a, **k: None)

    def fake_register(data_path, session_id):
        ic.ampcs_session_information.append({"data_path": data_path, "session_id": session_id})

    monkeypatch.setattr(ing_lib, "register_session", fake_register)


def _step(entries):
    return make_step("GDS_MANUAL", {"entries": entries})


class TestGdsManualStep:
    def test_success(self):
        # One positive and one negative session id to cover both filter branches.
        step = _step([
            {"data_path": "SIDE A", "session_id": 100},
            {"data_path": "SIDE B", "session_id": -1},
        ])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"

    def test_missing_data_path(self):
        step = _step([{"data_path": "  ", "session_id": 1}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"]["error_type"] == "USER_INPUT_ERROR"

    def test_shutdown_step_execution_error(self, monkeypatch):
        err = create_step_error(message="shutdown boom")
        monkeypatch.setattr(ing_lib, "ShutdownMTAK", lambda: (_ for _ in ()).throw(StepExecutionError("s", err)))
        step = _step([{"data_path": "SIDE A", "session_id": 1}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"] == err

    def test_shutdown_generic_error(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "ShutdownMTAK", lambda: (_ for _ in ()).throw(RuntimeError("x")))
        step = _step([{"data_path": "SIDE A", "session_id": 1}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"

    def test_start_step_execution_error(self, monkeypatch):
        err = create_step_error(message="start boom")
        monkeypatch.setattr(ing_lib, "StartMTAK", lambda **k: (_ for _ in ()).throw(StepExecutionError("s", err)))
        step = _step([{"data_path": "SIDE A", "session_id": 1}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"] == err

    def test_start_generic_error(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "StartMTAK", lambda **k: (_ for _ in ()).throw(RuntimeError("x")))
        step = _step([{"data_path": "SIDE A", "session_id": 1}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"

    def test_run_dummy(self):
        step = make_step("GDS_MANUAL", {"entries": [{"data_path": "SIDE A", "session_id": 1}]})
        result = step_mod.run_dummy(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"
        assert result["execution"]["results"]["entries"][0]["session_id"] == 1
