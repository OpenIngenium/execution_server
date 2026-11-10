"""Unit tests for ``ingenium_embedded.cmd_step`` (FSW/HW command dispatch).

Verification classes (``FSWVerify``/``HWVerify``), the dispatch calls
(``ing_lib.CommandFSW``/``CommandHW``), Core reporting, and ``time.sleep`` are
all mocked so no venue interaction or real waiting occurs.
"""

import pytest

from ingenium_embedded import cmd_step as step_mod
from ingenium_embedded import ingenium_library as ing_lib
from ingenium_embedded import ingenium_config as ic
from ingenium_embedded.ingenium_library import StepExecutionError, create_step_error

from mocks.test_helpers import make_step


@pytest.fixture(autouse=True)
def no_side_effects(monkeypatch):
    monkeypatch.setattr(step_mod, "report_step_results", lambda *a, **k: None)
    monkeypatch.setattr(step_mod.time, "sleep", lambda s: None)


def _step(entries, data_path="SIDE A"):
    return make_step("CMD", {"data_path": data_path, "entries": entries})


def _fake_verify_factory(verified=True):
    class _FakeVerify:
        def __init__(self, entry, data_path, step):
            self.entry = entry

        def fsw_command_verification(self):
            self.entry["verified"] = verified
            self.entry["radiated"] = True

        def hw_command_verfication(self):
            self.entry["verified"] = verified
            self.entry["radiated"] = True

    return _FakeVerify


class TestCmdStepDispatchNoVerify:
    def test_fsw_success(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "CommandFSW", lambda **k: {"dispatchTime": "t"})
        step = _step([{"cmd_string": "c", "verify": False, "hw_fsw": "FSW"}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"

    def test_hw_success(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "CommandHW", lambda **k: {"dispatchTime": "t"})
        step = _step([{"cmd_string": "c", "verify": False, "hw_fsw": "HW"}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"

    def test_fsw_not_radiated_fails(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "CommandFSW", lambda **k: {})
        step = _step([{"cmd_string": "c", "verify": False, "hw_fsw": "FSW"}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "FAIL"

    def test_fsw_step_execution_error(self, monkeypatch):
        err = create_step_error(message="boom")
        monkeypatch.setattr(ing_lib, "CommandFSW", lambda **k: (_ for _ in ()).throw(StepExecutionError("b", err)))
        step = _step([{"cmd_string": "c", "verify": False, "hw_fsw": "FSW"}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"] == err

    def test_fsw_generic_exception(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "CommandFSW", lambda **k: (_ for _ in ()).throw(ValueError("x")))
        step = _step([{"cmd_string": "c", "verify": False, "hw_fsw": "FSW"}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"

    def test_hw_step_execution_error(self, monkeypatch):
        err = create_step_error(message="boom")
        monkeypatch.setattr(ing_lib, "CommandHW", lambda **k: (_ for _ in ()).throw(StepExecutionError("b", err)))
        step = _step([{"cmd_string": "c", "verify": False, "hw_fsw": "HW"}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"

    def test_hw_generic_exception(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "CommandHW", lambda **k: (_ for _ in ()).throw(RuntimeError("x")))
        step = _step([{"cmd_string": "c", "verify": False, "hw_fsw": "HW"}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"


class TestCmdStepWithVerify:
    def test_fsw_verified_pass(self, monkeypatch):
        monkeypatch.setattr(step_mod, "FSWVerify", _fake_verify_factory(verified=True))
        step = _step([{"cmd_string": "c", "verify": True, "hw_fsw": "FSW"}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"

    def test_fsw_not_verified_fail(self, monkeypatch):
        monkeypatch.setattr(step_mod, "FSWVerify", _fake_verify_factory(verified=False))
        step = _step([{"cmd_string": "c", "verify": True, "hw_fsw": "FSW"}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "FAIL"

    def test_hw_verified_pass(self, monkeypatch):
        monkeypatch.setattr(step_mod, "HWVerify", _fake_verify_factory(verified=True))
        step = _step([{"cmd_string": "c", "verify": True, "hw_fsw": "HW"}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"

    def test_fsw_verify_step_execution_error(self, monkeypatch):
        err = create_step_error(message="verify boom")

        class _Boom:
            def __init__(self, **k):
                pass

            def fsw_command_verification(self):
                raise StepExecutionError("boom", err)

        monkeypatch.setattr(step_mod, "FSWVerify", _Boom)
        step = _step([{"cmd_string": "c", "verify": True, "hw_fsw": "FSW"}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"] == err

    def test_hw_verify_generic_exception(self, monkeypatch):
        class _Boom:
            def __init__(self, **k):
                pass

            def hw_command_verfication(self):
                raise RuntimeError("x")

        monkeypatch.setattr(step_mod, "HWVerify", _Boom)
        step = _step([{"cmd_string": "c", "verify": True, "hw_fsw": "HW"}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"


class TestCmdStepMisc:
    def test_missing_data_path_errors(self):
        step = _step([{"cmd_string": "c", "verify": False, "hw_fsw": "FSW"}], data_path="")
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"

    def test_run_dummy(self):
        ic.manual_input_variables["step_function_name"] = {"actual_value": "run_dummy"}
        step = _step([{"cmd_string": "c"}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"

    def test_run_dummy_get_session_info(self):
        ic.ampcs_session_information = [{"data_path": "SIDE A", "session_id": "1"}]
        step = _step([{"cmd_string": "c"}])
        result = step_mod.run_dummy_get_session_info(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"
        assert result["execution"]["results"]["entries"] == ic.ampcs_session_information
