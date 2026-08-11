"""Unit tests for ``ingenium_embedded.get_config_step``.

The venue-config query (``ing_lib.get_venue_config``) is mocked so no HTTP
occurs; tests exercise the found/not-found aggregation and error handling.
"""

import pytest

from ingenium_embedded import get_config_step as step_mod
from ingenium_embedded import ingenium_library as ing_lib
from ingenium_embedded import ingenium_config as ic
from ingenium_embedded.ingenium_library import StepExecutionError, create_step_error

from mocks.test_helpers import make_step


VENUE_CONFIG = [
    {"config_elem_name": "A", "type": "EM", "status": "INSTALLED", "serial": "1"},
    {"config_elem_name": "B", "type": "EM", "status": "INSTALLED", "serial": "2"},
]


def _make_step(entries, get_all=False):
    return make_step(
        "GET_CONFIG",
        {"entries": [{"config_elem_name": e} for e in entries], "get_all": get_all},
    )


class TestGetConfigStep:
    def test_get_all_returns_all_entries(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "get_venue_config", lambda: VENUE_CONFIG)
        step = _make_step([], get_all=True)
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"
        names = [e["config_elem_name"] for e in result["execution"]["results"]["entries"]]
        assert names == ["A", "B"]

    def test_specific_elements_found(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "get_venue_config", lambda: VENUE_CONFIG)
        step = _make_step(["A"], get_all=False)
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"

    def test_missing_element_fails(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "get_venue_config", lambda: VENUE_CONFIG)
        step = _make_step(["MISSING"], get_all=False)
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "FAIL"
        assert "MISSING" in result["execution"]["meta_data"]["message"]

    def test_step_execution_error_propagates_error_obj(self, monkeypatch):
        err = create_step_error(message="query boom")

        def boom():
            raise StepExecutionError("query boom", err)

        monkeypatch.setattr(ing_lib, "get_venue_config", boom)
        step = _make_step(["A"], get_all=False)
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"] == err

    def test_generic_exception_wrapped_as_error(self, monkeypatch):
        def boom():
            raise ValueError("unexpected")

        monkeypatch.setattr(ing_lib, "get_venue_config", boom)
        step = _make_step(["A"], get_all=False)
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"]["error_type"] == "QUERY_ERROR"

    def test_run_dummy_dispatch(self):
        ic.manual_input_variables["step_function_name"] = {"actual_value": "run_dummy"}
        step = _make_step(["A", "B"], get_all=False)
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"
        entries = result["execution"]["results"]["entries"]
        assert entries[0]["serial"] == "serial_number_0"
        assert entries[1]["serial"] == "serial_number_1"
