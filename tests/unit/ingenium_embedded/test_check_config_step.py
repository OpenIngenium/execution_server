"""Unit tests for ``ingenium_embedded.check_config_step``.

Input validation runs before any venue query, so those branches need no mocking.
The venue query (``ing_lib.get_venue_config``) is mocked for the evaluation
paths.
"""

from ingenium_embedded import check_config_step as step_mod
from ingenium_embedded import ingenium_library as ing_lib
from ingenium_embedded import ingenium_config as ic
from ingenium_embedded.ingenium_library import StepExecutionError, create_step_error

from mocks.test_helpers import make_step


def _entry(**over):
    entry = {
        "config_elem_name": "A",
        "field_name": "STATUS",
        "verification_condition": "EQUAL",
        "verification_value": "INSTALLED",
    }
    entry.update(over)
    return entry


def _step(entries):
    return make_step("CHECK_CONFIG", {"entries": entries})


class TestCheckConfigValidation:
    def test_invalid_verification_condition(self):
        step = _step([_entry(verification_condition="GREATER")])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"]["error_type"] == "USER_INPUT_ERROR"

    def test_invalid_field_name(self):
        step = _step([_entry(field_name="COLOR")])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"

    def test_invalid_type_value(self):
        step = _step([_entry(field_name="TYPE", verification_value="ALIEN")])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"

    def test_invalid_status_value(self):
        step = _step([_entry(field_name="STATUS", verification_value="MAYBE")])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"


class TestCheckConfigEvaluation:
    VENUE = [{"config_elem_name": "A", "type": "EM", "status": "INSTALLED", "serial": "1"}]

    def test_equal_pass(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "get_venue_config", lambda: self.VENUE)
        step = _step([_entry(field_name="STATUS", verification_condition="EQUAL", verification_value="INSTALLED")])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"

    def test_equal_fail(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "get_venue_config", lambda: self.VENUE)
        step = _step([_entry(field_name="STATUS", verification_condition="EQUAL", verification_value="NOT_INSTALLED")])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "FAIL"

    def test_not_equal_pass(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "get_venue_config", lambda: self.VENUE)
        step = _step([_entry(field_name="STATUS", verification_condition="NOT_EQUAL", verification_value="NOT_INSTALLED")])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"

    def test_element_not_found_fails(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "get_venue_config", lambda: self.VENUE)
        step = _step([_entry(config_elem_name="MISSING")])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "FAIL"
        entry = result["execution"]["results"]["entries"][0]
        assert entry["actual_value"] == "NOT PRESENT ON VENUE"

    def test_query_step_execution_error(self, monkeypatch):
        err = create_step_error(message="boom")

        def boom():
            raise StepExecutionError("boom", err)

        monkeypatch.setattr(ing_lib, "get_venue_config", boom)
        step = _step([_entry()])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"] == err

    def test_query_generic_exception(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "get_venue_config", lambda: (_ for _ in ()).throw(ValueError("x")))
        step = _step([_entry()])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"]["error_type"] == "QUERY_ERROR"


class TestCheckConfigDummy:
    def test_run_dummy(self):
        ic.manual_input_variables["step_function_name"] = {"actual_value": "run_dummy"}
        step = _step([_entry(verification_value="INSTALLED")])
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"
        entry = result["execution"]["results"]["entries"][0]
        assert entry["actual_value"] == "INSTALLED"
        assert entry["verification_status"] == "PASS"
