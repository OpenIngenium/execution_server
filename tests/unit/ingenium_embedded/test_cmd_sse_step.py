"""Unit tests for ``ingenium_embedded.cmd_sse_step``.

``ing_lib.CommandSSE`` (the venue dispatch call) and Core reporting are mocked.
"""

import pytest

from ingenium_embedded import cmd_sse_step as step_mod
from ingenium_embedded import ingenium_library as ing_lib
from ingenium_embedded import ingenium_config as ic
from ingenium_embedded.ingenium_library import StepExecutionError, create_step_error

from mocks.test_helpers import make_step


@pytest.fixture(autouse=True)
def no_report(monkeypatch):
    monkeypatch.setattr(step_mod, "report_step_results", lambda *a, **k: None)


def _step(entries, data_path="SIDE A"):
    ui = {"data_path": data_path, "entries": entries}
    return make_step("CMD_SSE", ui)


class TestCmdSseStep:
    def test_success_radiated(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "CommandSSE", lambda **k: {"dispatchTime": "2020-001T00:00:00"})
        step = _step([{"cmd_string": "sse cmd"}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"
        assert result["execution"]["results"]["entries"][0]["radiated"] is True

    def test_not_radiated_fails(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "CommandSSE", lambda **k: {})
        step = _step([{"cmd_string": "sse cmd"}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "FAIL"

    def test_missing_data_path_errors(self):
        step = _step([{"cmd_string": "x"}], data_path="")
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"]["error_type"] == "USER_INPUT_ERROR"

    def test_step_execution_error(self, monkeypatch):
        err = create_step_error(message="dispatch boom")

        def boom(**k):
            raise StepExecutionError("boom", err)

        monkeypatch.setattr(ing_lib, "CommandSSE", boom)
        step = _step([{"cmd_string": "x"}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"] == err

    def test_generic_exception(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "CommandSSE", lambda **k: (_ for _ in ()).throw(ValueError("x")))
        step = _step([{"cmd_string": "x"}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"]["error_type"] == "DISPATCH_ERROR"

    def test_run_dummy(self):
        ic.manual_input_variables["step_function_name"] = {"actual_value": "run_dummy"}
        step = _step([{"cmd_string": "x"}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"
        assert result["execution"]["results"]["entries"][0]["radiated"] is True
