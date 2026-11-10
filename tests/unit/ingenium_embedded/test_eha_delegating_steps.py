"""Unit tests for the thin EHA step wrappers ``verify_eha_step`` and
``wait_eha_step``.

Both delegate to ``verification_lib.run_eha_verification``; the collaborator is
mocked so tests verify the delegation contract and the dummy fallback.
"""

from ingenium_embedded import verify_eha_step
from ingenium_embedded import wait_eha_step
from ingenium_embedded import ingenium_config as ic

from mocks.test_helpers import make_step


class TestVerifyEhaStep:
    def test_delegates_with_recorded_false(self, monkeypatch):
        captured = {}

        def fake_verify(step, recorded):
            captured["recorded"] = recorded
            step["execution"]["meta_data"]["status"] = "PASS"
            return step

        monkeypatch.setattr(verify_eha_step, "run_eha_verification", fake_verify)
        step = make_step("VERIFY_EHA", {"entries": []})
        result = verify_eha_step.run(step)
        assert captured["recorded"] is False
        assert result["execution"]["meta_data"]["status"] == "PASS"

    def test_run_dummy(self):
        ic.manual_input_variables["step_function_name"] = {"actual_value": "run_dummy"}
        step = make_step("VERIFY_EHA", {"entries": [{"channel_id": "X"}]})
        result = verify_eha_step.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"
        assert len(result["execution"]["results"]["entries"]) == 1


class TestWaitEhaStep:
    def test_delegates_with_recorded_true(self, monkeypatch):
        captured = {}

        def fake_verify(step, recorded):
            captured["recorded"] = recorded
            step["execution"]["meta_data"]["status"] = "PASS"
            return step

        monkeypatch.setattr(wait_eha_step, "run_eha_verification", fake_verify)
        step = make_step("WAIT_EHA", {"entries": []})
        result = wait_eha_step.run(step)
        assert captured["recorded"] is True
        assert result["execution"]["meta_data"]["status"] == "PASS"

    def test_run_dummy(self):
        ic.manual_input_variables["step_function_name"] = {"actual_value": "run_dummy"}
        step = make_step("WAIT_EHA", {"entries": [{"channel_id": "X"}, {"channel_id": "Y"}]})
        result = wait_eha_step.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"
        assert len(result["execution"]["results"]["entries"]) == 2
