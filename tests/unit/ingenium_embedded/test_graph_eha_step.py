"""Unit tests for ``ingenium_embedded.graph_eha_step``.

``validate_times`` and ``ing_lib.ChillEHAQuery`` are mocked.
"""

import pytest

from ingenium_embedded import graph_eha_step as step_mod
from ingenium_embedded import ingenium_library as ing_lib
from ingenium_embedded import ingenium_config as ic
from ingenium_embedded.ingenium_library import StepExecutionError, create_step_error

from mocks.test_helpers import make_step


TIMES = ("ts", "te", "s", "e")


@pytest.fixture(autouse=True)
def patch_times(monkeypatch):
    monkeypatch.setattr(step_mod, "validate_times", lambda results, step_type: TIMES)


def _step(data_path="SIDE A", dn_eu="DN", **ui):
    base = {"data_path": data_path, "dn_eu": dn_eu}
    base.update(ui)
    return make_step("GRAPH_EHA", base)


class TestGraphEhaStep:
    def test_success_with_data(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "ChillEHAQuery", lambda **k: [{"ert": "2020-100T00:00:00", "dn": "34.5"}])
        step = _step()
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"
        assert result["execution"]["results"]["channel_data"][0]["value"] == "34.5"

    def test_no_data_fails(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "ChillEHAQuery", lambda **k: [])
        step = _step()
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "FAIL"

    def test_missing_data_path(self):
        step = _step(data_path="")
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"

    def test_non_string_channel_type(self):
        step = _step(channel_type=123)
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"]["error_type"] == "USER_INPUT_ERROR"

    def test_validate_times_error(self, monkeypatch):
        err = create_step_error(message="t")
        monkeypatch.setattr(step_mod, "validate_times", lambda r, s: (_ for _ in ()).throw(StepExecutionError("t", err)))
        step = _step()
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"] == err

    def test_query_step_execution_error(self, monkeypatch):
        err = create_step_error(message="q")
        monkeypatch.setattr(ing_lib, "ChillEHAQuery", lambda **k: (_ for _ in ()).throw(StepExecutionError("q", err)))
        step = _step()
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"] == err

    def test_query_generic_exception(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "ChillEHAQuery", lambda **k: (_ for _ in ()).throw(ValueError("x")))
        step = _step()
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"]["error_type"] == "QUERY_ERROR"

    def test_run_dummy(self):
        ic.manual_input_variables["step_function_name"] = {"actual_value": "run_dummy"}
        step = _step()
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"
        assert len(result["execution"]["results"]["channel_data"]) == 2
