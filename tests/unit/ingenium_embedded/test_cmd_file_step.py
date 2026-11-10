"""Unit tests for ``ingenium_embedded.cmd_file_step`` (binary file dispatch).

``BinaryFileVerify``, ``ing_lib.CommandBinaryFile``, and Core reporting are
mocked.
"""

import pytest

from ingenium_embedded import cmd_file_step as step_mod
from ingenium_embedded import ingenium_library as ing_lib
from ingenium_embedded import ingenium_config as ic
from ingenium_embedded.ingenium_library import StepExecutionError, create_step_error

from mocks.test_helpers import make_step


@pytest.fixture(autouse=True)
def no_report(monkeypatch):
    monkeypatch.setattr(step_mod, "report_step_results", lambda *a, **k: None)


def _entry(**over):
    entry = {
        "file_type": "0",
        "file_path": "/src/file.bin",
        "onboard_path": "/dst/file.bin",
        "verify": False,
    }
    entry.update(over)
    return entry


def _step(entries, data_path="SIDE A"):
    return make_step("CMD_FILE", {"data_path": data_path, "entries": entries})


class TestCmdFileStep:
    def test_success_no_verify(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "CommandBinaryFile", lambda **k: {"dispatchTime": "t"})
        step = _step([_entry(verify=False)])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"
        assert result["execution"]["results"]["entries"][0]["radiated"] is True

    def test_not_radiated_fails(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "CommandBinaryFile", lambda **k: {})
        step = _step([_entry(verify=False)])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "FAIL"

    def test_verify_success(self, monkeypatch):
        class _FakeVerify:
            def __init__(self, entry, data_path, step):
                self.entry = entry

            def binary_file_verification(self):
                self.entry["verified"] = True
                self.entry["radiated"] = True

        monkeypatch.setattr(step_mod, "BinaryFileVerify", _FakeVerify)
        step = _step([_entry(verify=True)])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"

    def test_verify_step_execution_error(self, monkeypatch):
        err = create_step_error(message="boom")

        class _Boom:
            def __init__(self, **k):
                pass

            def binary_file_verification(self):
                raise StepExecutionError("boom", err)

        monkeypatch.setattr(step_mod, "BinaryFileVerify", _Boom)
        step = _step([_entry(verify=True)])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"] == err

    def test_invalid_file_type_errors(self):
        step = _step([_entry(file_type="abc")])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"]["error_type"] == "USER_INPUT_ERROR"

    def test_missing_data_path_errors(self):
        step = _step([_entry()], data_path="")
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"

    def test_dispatch_step_execution_error(self, monkeypatch):
        err = create_step_error(message="boom")
        monkeypatch.setattr(ing_lib, "CommandBinaryFile", lambda **k: (_ for _ in ()).throw(StepExecutionError("b", err)))
        step = _step([_entry(verify=False)])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"] == err

    def test_dispatch_generic_exception(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "CommandBinaryFile", lambda **k: (_ for _ in ()).throw(ValueError("x")))
        step = _step([_entry(verify=False)])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"]["error_type"] == "DISPATCH_ERROR"

    def test_run_dummy(self):
        ic.manual_input_variables["step_function_name"] = {"actual_value": "run_dummy"}
        step = _step([_entry()])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"
