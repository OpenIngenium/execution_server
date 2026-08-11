"""Unit tests for ``ingenium_embedded.cmd_scmf_step``.

``ing_lib.CommandSCMF`` and Core reporting are mocked.
"""

import pytest

from ingenium_embedded import cmd_scmf_step as step_mod
from ingenium_embedded import ingenium_library as ing_lib
from ingenium_embedded import ingenium_config as ic
from ingenium_embedded.ingenium_library import StepExecutionError, create_step_error

from mocks.test_helpers import make_step


@pytest.fixture(autouse=True)
def no_report(monkeypatch):
    monkeypatch.setattr(step_mod, "report_step_results", lambda *a, **k: None)


def _step(entries, data_path="SIDE A"):
    return make_step("CMD_SCMF", {"data_path": data_path, "entries": entries})


class TestCmdScmfStep:
    def test_success(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "CommandSCMF", lambda **k: {"dispatchTime": "2020-001T00:00:00"})
        step = _step([{"file_path": "/a/b/file.scmf", "verify": False}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"
        entry = result["execution"]["results"]["entries"][0]
        assert entry["radiated"] is True
        assert entry["scmf_name"] == "file.scmf"

    def test_not_radiated_fails(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "CommandSCMF", lambda **k: {})
        step = _step([{"file_path": "/a/file.scmf", "verify": False}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "FAIL"

    def test_missing_data_path_errors(self):
        step = _step([{"file_path": "/a/file.scmf"}], data_path="")
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"

    def test_step_execution_error(self, monkeypatch):
        err = create_step_error(message="boom")

        def boom(**k):
            raise StepExecutionError("boom", err)

        monkeypatch.setattr(ing_lib, "CommandSCMF", boom)
        step = _step([{"file_path": "/a/file.scmf", "verify": False}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"] == err

    def test_generic_exception(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "CommandSCMF", lambda **k: (_ for _ in ()).throw(RuntimeError("x")))
        step = _step([{"file_path": "/a/file.scmf", "verify": False}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"]["error_type"] == "DISPATCH_ERROR"

    def test_run_dummy(self):
        ic.manual_input_variables["step_function_name"] = {"actual_value": "run_dummy"}
        step = _step([{"file_path": "/a/file.scmf"}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"
