"""Unit tests for the pure business-logic helpers in ``execution_server``.

These cover the step-selection / pause / dispatch logic that the retired
integration test ``tests/test_ci_execution_server.py`` previously exercised
end-to-end over HTTP. The Tornado request handlers, the ``ProcessPoolExecutor``
worker machinery, and the ``run_execution`` Core-orchestration loop remain
integration-scope and are not unit-tested here.
"""

from unittest.mock import MagicMock

import pytest

import execution_server as es


class TestGetPid:
    def test_returns_int(self):
        assert isinstance(es.get_pid(), int)


class TestGetStepIdx:
    ELEMS = [{"elem_id": "a"}, {"elem_id": "b"}, {"elem_id": "c"}]

    def test_empty_id_returns_first(self):
        assert es.get_step_idx(self.ELEMS, "") == 0

    def test_found(self):
        assert es.get_step_idx(self.ELEMS, "b") == 1

    def test_not_found(self):
        assert es.get_step_idx(self.ELEMS, "missing") == -1


class TestNeedsApproval:
    def test_non_step_type_false(self):
        assert es.needs_approval({"elem_type": "SECTION"}) is False

    def test_unmodified_step_false(self):
        assert es.needs_approval({"elem_type": "STEP", "procedure_modification_status": "NONE"}) is False

    def test_modifying_without_modification_true(self):
        elem = {"elem_type": "STEP", "procedure_modification_status": "MODIFYING", "procedure_modification": None}
        assert es.needs_approval(elem) is True

    def test_added_without_approval_true(self):
        elem = {"elem_type": "STEP", "procedure_modification_status": "ADDED", "procedure_modification": {}}
        assert es.needs_approval(elem) is True

    def test_approved_false(self):
        elem = {
            "elem_type": "STEP",
            "procedure_modification_status": "DELETED",
            "procedure_modification": {"approval": {"status": "APPROVED"}},
        }
        assert es.needs_approval(elem) is False

    def test_not_approved_true(self):
        elem = {
            "elem_type": "STEP",
            "procedure_modification_status": "MODIFYING",
            "procedure_modification": {"approval": {"status": "PENDING"}},
        }
        assert es.needs_approval(elem) is True


class TestRequiresManualInput:
    def test_manual_step_type(self):
        assert es.requires_manual_input({"elem_type": "STEP", "step_type": "MANUAL_INPUT"}) is True

    def test_non_manual_step(self):
        assert es.requires_manual_input({"elem_type": "STEP", "step_type": "WAIT_STEP"}) is None or \
            es.requires_manual_input({"elem_type": "STEP", "step_type": "WAIT_STEP"}) is False

    def test_custom_script_execution_input(self):
        elem = {
            "elem_type": "STEP",
            "step_type": "CUSTOM_SCRIPT",
            "execution_user_input": {"inputs": [{"phase": "EXECUTION"}]},
        }
        assert es.requires_manual_input(elem) is True

    def test_custom_script_entry_input(self):
        elem = {
            "elem_type": "STEP",
            "step_type": "CUSTOM_SCRIPT",
            "execution_user_input": {"entries": [{"entry_inputs": [{"phase": "EXECUTION"}]}]},
        }
        assert es.requires_manual_input(elem) is True

    def test_custom_script_no_execution_input(self):
        elem = {
            "elem_type": "STEP",
            "step_type": "CUSTOM_SCRIPT",
            "execution_user_input": {"inputs": [{"phase": "SETUP"}]},
        }
        assert es.requires_manual_input(elem) is False

    def test_non_step_false(self):
        assert es.requires_manual_input({"elem_type": "SECTION"}) is False


class TestIsCommandStep:
    @pytest.mark.parametrize("step_type", ["CMD", "CMD_SSE", "CMD_FILE", "CUSTOM_SCRIPT"])
    def test_command_types(self, step_type):
        assert es.is_command_step({"elem_type": "STEP", "step_type": step_type}) is True

    def test_non_command(self):
        assert es.is_command_step({"elem_type": "STEP", "step_type": "WAIT_STEP"}) is False

    def test_non_step(self):
        assert es.is_command_step({"elem_type": "SECTION", "step_type": "CMD"}) is False


class TestRunStep:
    def test_dispatches_to_module_function(self, monkeypatch):
        monkeypatch.setattr(es, "refresh_venue_tokens", lambda: None)
        fake_module = MagicMock()
        fake_module.run.return_value = {"dispatched": True}
        monkeypatch.setattr(es.importlib, "import_module", lambda name: fake_module)

        step = {"code": {"name": "wait_step.run"}, "execution_id": 1}
        result = es.run_step(step)
        assert result == {"dispatched": True}
        fake_module.run.assert_called_once_with(step)

    def test_invalid_code_name_raises(self, monkeypatch):
        monkeypatch.setattr(es, "refresh_venue_tokens", lambda: None)
        with pytest.raises(Exception):
            es.run_step({"code": {"name": "badformat"}})
