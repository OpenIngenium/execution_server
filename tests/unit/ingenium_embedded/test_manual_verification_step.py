"""Unit tests for ``ingenium_embedded.manual_verification_step``."""

from ingenium_embedded import manual_verification_step as step_mod
from ingenium_embedded import ingenium_config as ic

from mocks.test_helpers import make_step


class TestManualVerificationStep:
    def test_pass_status(self):
        step = make_step("MANUAL_VERIFICATION", {"verification_status": "PASS"})
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"

    def test_fail_status(self):
        step = make_step("MANUAL_VERIFICATION", {"verification_status": "FAIL"})
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "FAIL"

    def test_non_pass_value_is_treated_as_fail(self):
        step = make_step("MANUAL_VERIFICATION", {"verification_status": "anything"})
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "FAIL"

    def test_run_dummy_dispatch(self):
        ic.variables["step_function_name"] = "run_dummy"
        step = make_step("MANUAL_VERIFICATION", {"verification_status": "FAIL"})
        result = step_mod.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"
