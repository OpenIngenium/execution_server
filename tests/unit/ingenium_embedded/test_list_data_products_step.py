"""Unit tests for ``ingenium_embedded.list_data_products_step``.

``validate_times``, ``DpResponse`` and ``ing_lib.DataProductsQuery`` are mocked.
"""

import pytest

from ingenium_embedded import list_data_products_step as step_mod
from ingenium_embedded import ingenium_library as ing_lib
from ingenium_embedded import ingenium_config as ic
from ingenium_embedded.ingenium_library import StepExecutionError, create_step_error

from mocks.test_helpers import make_step


TIMES = ("s", "e", "s", "e")


def _fake_dp_response(status="PASS"):
    class _FakeDpResponse:
        def __init__(self, entries, *a):
            self.entries = [dict(e) for e in entries]
            self.payload = {"entries": self.entries}

        def return_intermediate_response(self):
            return self.payload

        def update_dp_entry(self, index, data_products, total_count):
            self.entries[index]["verification_status"] = status
            self.entries[index]["total_count"] = total_count

    return _FakeDpResponse


@pytest.fixture(autouse=True)
def patch_times(monkeypatch):
    monkeypatch.setattr(step_mod, "validate_times", lambda results, step_type: TIMES)


def _step(entries, data_path="SIDE A"):
    return make_step("LIST_DP", {"data_path": data_path, "entries": entries})


class TestListDataProductsStep:
    def test_success_pass(self, monkeypatch):
        monkeypatch.setattr(step_mod, "DpResponse", _fake_dp_response("PASS"))
        monkeypatch.setattr(ing_lib, "DataProductsQuery", lambda **k: [{"apid": 1}])
        step = _step([{"apid": 1}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"

    def test_fail_status(self, monkeypatch):
        monkeypatch.setattr(step_mod, "DpResponse", _fake_dp_response("FAIL"))
        monkeypatch.setattr(ing_lib, "DataProductsQuery", lambda **k: [])
        step = _step([{"apid": 1}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "FAIL"

    def test_invalid_status_filter(self, monkeypatch):
        monkeypatch.setattr(step_mod, "DpResponse", _fake_dp_response())
        step = _step([{"apid": 1, "product_status_filter": "BOGUS"}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"

    def test_missing_data_path(self, monkeypatch):
        monkeypatch.setattr(step_mod, "DpResponse", _fake_dp_response())
        step = _step([{"apid": 1}], data_path="")
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"

    def test_validate_times_error(self, monkeypatch):
        err = create_step_error(message="t")
        monkeypatch.setattr(step_mod, "validate_times", lambda r, s: (_ for _ in ()).throw(StepExecutionError("t", err)))
        step = _step([{"apid": 1}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"] == err

    def test_query_step_execution_error(self, monkeypatch):
        monkeypatch.setattr(step_mod, "DpResponse", _fake_dp_response())
        err = create_step_error(message="q")
        monkeypatch.setattr(ing_lib, "DataProductsQuery", lambda **k: (_ for _ in ()).throw(StepExecutionError("q", err)))
        step = _step([{"apid": 1}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"] == err

    def test_query_generic_exception(self, monkeypatch):
        monkeypatch.setattr(step_mod, "DpResponse", _fake_dp_response())
        monkeypatch.setattr(ing_lib, "DataProductsQuery", lambda **k: (_ for _ in ()).throw(ValueError("x")))
        step = _step([{"apid": 1}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"]["error_type"] == "QUERY_ERROR"

    def test_non_list_response_errors(self, monkeypatch):
        monkeypatch.setattr(step_mod, "DpResponse", _fake_dp_response())
        monkeypatch.setattr(ing_lib, "DataProductsQuery", lambda **k: "not-a-list")
        step = _step([{"apid": 1}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"

    def test_run_dummy(self):
        ic.manual_input_variables["step_function_name"] = {"actual_value": "run_dummy"}
        step = _step([{"apid": 1}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"
