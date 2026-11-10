"""Unit tests for ``ingenium_embedded.custom_script_step``.

All venue collaborators (script start/status/halt, file processing, token
refresh, reporting) plus the wall clock and sleep are mocked so the polling loop
is deterministic and fast.
"""

import pytest

from ingenium_embedded import custom_script_step as step_mod
from ingenium_embedded import ingenium_library as ing_lib
from ingenium_embedded import ingenium_config as ic
from ingenium_embedded.ingenium_library import StepExecutionError, create_step_error

from mocks.test_helpers import make_step
from mocks.mock_http_client import make_response


class _FakeClock:
    def __init__(self, step=1.0):
        self.t = 0.0
        self.step = step

    def time(self):
        v = self.t
        self.t += self.step
        return v


def _fake_csr():
    class _FakeCSR:
        def __init__(self, step_input):
            self.payload = {"custom_script_status": "PENDING"}

        def return_intermediate_response(self):
            return self.payload

        def update_outputs_with_results(self, info):
            self.payload["custom_script_status"] = info.get("custom_script_status")

        def return_script_status(self):
            return self.payload["custom_script_status"]

        def update_logfile_url(self, url):
            self.payload["logfile_url"] = url

    return _FakeCSR


@pytest.fixture(autouse=True)
def patch_common(monkeypatch):
    monkeypatch.setattr(step_mod, "CustomScriptResponse", _fake_csr())
    monkeypatch.setattr(step_mod, "refresh_venue_tokens", lambda *a, **k: None)
    monkeypatch.setattr(step_mod, "report_step_results", lambda *a, **k: None)
    monkeypatch.setattr(step_mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(step_mod.time, "time", _FakeClock().time)
    monkeypatch.setattr(ing_lib, "start_custom_script", lambda step_input: {"scriptRunId": "rid"})
    monkeypatch.setattr(ing_lib, "store_custom_script_session_id", lambda *a, **k: None)
    monkeypatch.setattr(ing_lib, "halt_script", lambda *a, **k: None)


def _valid_input(**over):
    ui = {"script_name": "s.sh", "hash": "abc", "script_path": "/p/s.sh", "timeout": 100}
    ui.update(over)
    return ui


def _step(**over):
    return make_step("CUSTOM_SCRIPT", _valid_input(**over))


class TestCustomScriptValidation:
    def test_missing_script_name(self):
        step = make_step("CUSTOM_SCRIPT", {"hash": "a", "script_path": "/p"})
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"

    def test_missing_hash(self):
        step = make_step("CUSTOM_SCRIPT", {"script_name": "s", "script_path": "/p"})
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"

    def test_missing_script_path(self):
        step = make_step("CUSTOM_SCRIPT", {"script_name": "s", "hash": "a"})
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"


class TestCustomScriptStart:
    def test_start_step_execution_error(self, monkeypatch):
        err = create_step_error(message="start boom")
        monkeypatch.setattr(ing_lib, "start_custom_script", lambda step_input: (_ for _ in ()).throw(StepExecutionError("s", err)))
        result = step_mod.run(_step())
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"] == err

    def test_start_generic_error(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "start_custom_script", lambda step_input: (_ for _ in ()).throw(RuntimeError("x")))
        result = step_mod.run(_step())
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"]["error_type"] == "QUERY_ERROR"


class TestCustomScriptPolling:
    def test_pass(self, monkeypatch):
        response = make_response(200, json_data={"custom_script_status": "PASS", "logfile_lines": ["ok"], "logfile_url": None})
        monkeypatch.setattr(ing_lib, "get_script_status", lambda rid: response)
        result = step_mod.run(_step())
        assert result["execution"]["meta_data"]["status"] == "PASS"

    def test_error_status(self, monkeypatch):
        response = make_response(200, json_data={"custom_script_status": "ERROR", "logfile_lines": ["bad"], "logfile_url": None})
        monkeypatch.setattr(ing_lib, "get_script_status", lambda rid: response)
        result = step_mod.run(_step())
        assert result["execution"]["meta_data"]["status"] == "FAIL"
        assert result["execution"]["meta_data"]["error"]["error_type"] == "STEP_ERROR"

    def test_timeout(self, monkeypatch):
        # Status stays PENDING; clock advances past the small timeout.
        response = make_response(200, json_data={"custom_script_status": "PENDING", "logfile_lines": ["still going"], "logfile_url": None})
        monkeypatch.setattr(ing_lib, "get_script_status", lambda rid: response)
        halted = []
        monkeypatch.setattr(ing_lib, "halt_script", lambda rid: halted.append(rid))
        result = step_mod.run(_step(timeout=2))
        assert result["execution"]["meta_data"]["status"] == "FAIL"
        assert result["execution"]["meta_data"]["error"]["error_type"] == "TIMEOUT"
        assert halted == ["rid"]

    def test_status_query_non_200_then_timeout(self, monkeypatch):
        response = make_response(500, text="server error")
        monkeypatch.setattr(ing_lib, "get_script_status", lambda rid: response)
        result = step_mod.run(_step(timeout=2))
        assert result["execution"]["meta_data"]["status"] == "FAIL"

    def test_status_query_exception_then_timeout(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "get_script_status", lambda rid: (_ for _ in ()).throw(RuntimeError("net")))
        result = step_mod.run(_step(timeout=2))
        assert result["execution"]["meta_data"]["status"] == "FAIL"


class TestCustomScriptFiles:
    def test_process_files_updates_state(self, monkeypatch):
        response = make_response(200, json_data={"custom_script_status": "PASS", "logfile_lines": ["ok"], "logfile_url": "http://logs/tar"})
        monkeypatch.setattr(ing_lib, "get_script_status", lambda rid: response)
        output_json = {"states": {"variables": {"v1": 1}, "channel_variables": {"c1": 2},
                                   "manual_input_variables": {"m1": 3}, "mil_1553_variables": {"b1": 4}}}
        monkeypatch.setattr(ing_lib, "process_cs_files", lambda url, rid, csr: ("http://fs/log", output_json))
        result = step_mod.run(_step())
        assert result["execution"]["meta_data"]["status"] == "PASS"
        assert ic.variables["v1"] == 1
        assert ic.channel_variables["c1"] == 2
        assert ic.manual_input_variables["m1"] == 3
        assert ic.mil_1553_variables["b1"] == 4

    def test_process_files_step_execution_error(self, monkeypatch):
        response = make_response(200, json_data={"custom_script_status": "PASS", "logfile_lines": ["ok"], "logfile_url": "http://logs/tar"})
        monkeypatch.setattr(ing_lib, "get_script_status", lambda rid: response)
        err = create_step_error(message="tar boom")
        monkeypatch.setattr(ing_lib, "process_cs_files", lambda *a, **k: (_ for _ in ()).throw(StepExecutionError("t", err)))
        result = step_mod.run(_step())
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"] == err
