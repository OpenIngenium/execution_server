"""Unit tests for ``ingenium_embedded.update_config_step``.

``ing_lib.update_venue_config`` is mocked so no HTTP occurs.
"""

from ingenium_embedded import update_config_step as step_mod
from ingenium_embedded import ingenium_library as ing_lib
from ingenium_embedded import ingenium_config as ic
from ingenium_embedded.ingenium_library import StepExecutionError, create_step_error

from mocks.test_helpers import make_step


def _make_step(entries):
    return make_step("UPDATE_CONFIG", {"entries": entries})


class TestUpdateConfigStep:
    def test_success_updates_and_renames_key(self, monkeypatch):
        def fake_update(entry):
            return {"elem_name": entry["config_elem_name"], "status": "INSTALLED"}

        monkeypatch.setattr(ing_lib, "update_venue_config", fake_update)
        step = _make_step([{"config_elem_name": "A"}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"
        entry = result["execution"]["results"]["entries"][0]
        assert entry["config_elem_name"] == "A"
        assert "elem_name" not in entry

    def test_step_execution_error_returns_error_obj(self, monkeypatch):
        err = create_step_error(message="update boom")

        def boom(entry):
            raise StepExecutionError("update boom", err)

        monkeypatch.setattr(ing_lib, "update_venue_config", boom)
        step = _make_step([{"config_elem_name": "A"}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"] == err

    def test_generic_exception_wrapped(self, monkeypatch):
        def boom(entry):
            raise RuntimeError("kaboom")

        monkeypatch.setattr(ing_lib, "update_venue_config", boom)
        step = _make_step([{"config_elem_name": "A"}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"]["error_type"] == "QUERY_ERROR"

    def test_run_dummy_dispatch(self):
        ic.manual_input_variables["step_function_name"] = {"actual_value": "run_dummy"}
        ic.venue_id = "v1"
        ic.venue_name = "venue-one"
        step = _make_step([{"config_elem_name": "A"}])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"
        assert result["execution"]["results"]["venue_id"] == "v1"
        assert result["execution"]["results"]["venue_name"] == "venue-one"
