"""Unit tests for ``verification_lib`` command verification
(``CommandBase.verify_command`` via FSWVerify / HWVerify / BinaryFileVerify).

The subclass query/dispatch hooks are mocked so the verification state machine
is exercised without any venue queries or real waiting.
"""

from unittest.mock import Mock

import pytest

from ingenium_embedded import verification_lib as vlib
from ingenium_embedded import ingenium_library as ing_lib
from ingenium_embedded import ingenium_config as ic
from ingenium_embedded.verification_lib import FSWVerify, HWVerify, BinaryFileVerify
from ingenium_embedded.ingenium_library import StepExecutionError

from mocks.test_helpers import make_step


@pytest.fixture(autouse=True)
def patch_common(monkeypatch):
    monkeypatch.setattr(ing_lib, "get_session_information", lambda dp: 5)
    monkeypatch.setattr(ing_lib, "get_telemetry_query_time", lambda *a, **k: ("s", "e"))
    monkeypatch.setattr(ing_lib, "report_step_results", lambda *a, **k: None)
    monkeypatch.setattr(vlib.time, "sleep", lambda s: None)


def _fsw(entry=None):
    entry = entry or {"hw_fsw": "FSW", "cmd_string": "flight 1 2", "string_selection": "DEFAULT"}
    return FSWVerify(entry, "SIDE A", make_step("CMD", {"entries": [entry]}))


def _wire(ver, eha_values, dispatch, evrs):
    """Attach mocked telemetry/dispatch hooks to a verifier instance."""
    ver.query_eha_telemetry = Mock(side_effect=[[{"dn": str(v)}] for v in eha_values])
    ver.dispatch_cmd = Mock(return_value=dispatch)
    ver.query_evr_telemetry = Mock(return_value=evrs)


class TestFswVerify:
    def test_success_verified(self):
        ver = _fsw()
        _wire(ver, eha_values=[5, 6], dispatch={"dispatchTime": "t"}, evrs=[{"ert": "t"}])
        ver.fsw_command_verification()
        assert ver.entry["radiated"] is True
        assert ver.entry["verified"] is True

    def test_value_unchanged_then_incremented(self):
        ver = _fsw()
        # Initial value 5, verification reads 6 -> +1 -> verified.
        _wire(ver, eha_values=[5, 6], dispatch={"dispatchTime": "t"}, evrs=[{"ert": "t"}])
        ver.fsw_command_verification()
        assert ver.entry["verified"] is True

    def test_value_incremented_more_than_one_fails(self):
        ver = _fsw()
        _wire(ver, eha_values=[5, 7], dispatch={"dispatchTime": "t"}, evrs=[{"ert": "t"}])
        ver.fsw_command_verification()
        assert ver.entry["verified"] is False

    def test_no_evr_returns_unverified(self):
        ver = _fsw()
        _wire(ver, eha_values=[5], dispatch={"dispatchTime": "t"}, evrs=[])
        ver.fsw_command_verification()
        assert ver.entry["radiated"] is True
        assert ver.entry["verified"] is False

    def test_dispatch_string_raises(self):
        ver = _fsw()
        ver.query_eha_telemetry = Mock(return_value=[{"dn": "5"}])
        ver.dispatch_cmd = Mock(return_value="dispatch error")
        ver.query_evr_telemetry = Mock(return_value=[])
        with pytest.raises(StepExecutionError):
            ver.fsw_command_verification()

    def test_dispatch_message_raises(self):
        ver = _fsw()
        ver.query_eha_telemetry = Mock(return_value=[{"dn": "5"}])
        ver.dispatch_cmd = Mock(return_value={"message": "bad"})
        ver.query_evr_telemetry = Mock(return_value=[])
        with pytest.raises(StepExecutionError):
            ver.fsw_command_verification()

    def test_initial_eha_empty_raises(self):
        ver = _fsw()
        ver.query_eha_telemetry = Mock(return_value=[])
        ver.dispatch_cmd = Mock(return_value={"dispatchTime": "t"})
        ver.query_evr_telemetry = Mock(return_value=[{"ert": "t"}])
        with pytest.raises(StepExecutionError):
            ver.fsw_command_verification()

    def test_dispatch_step_execution_error_wrapped(self):
        ver = _fsw()
        ver.query_eha_telemetry = Mock(return_value=[{"dn": "5"}])
        ver.dispatch_cmd = Mock(side_effect=StepExecutionError("boom", {}))
        with pytest.raises(StepExecutionError):
            ver.fsw_command_verification()


class TestHwVerify:
    def test_success(self):
        entry = {"hw_fsw": "HW", "cmd_string": "stem", "string_selection": "DEFAULT"}
        ver = HWVerify(entry, "SIDE A", make_step("CMD", {"entries": [entry]}))
        _wire(ver, eha_values=[10, 11], dispatch={"dispatchTime": "t"}, evrs=[{"ert": "t"}])
        ver.hw_command_verfication()
        assert ver.entry["verified"] is True


class TestBinaryFileVerify:
    def test_success_no_channels(self):
        # binary_file_channels defaults to empty -> verification skips EHA checks.
        entry = {"file_type": "0", "file_path": "/s", "onboard_path": "/t", "overwrite": True}
        ver = BinaryFileVerify(entry, "SIDE A", make_step("CMD_FILE", {"entries": [entry]}))
        ver.query_eha_telemetry = Mock(return_value=[{"dn": "5"}])
        ver.dispatch_cmd = Mock(return_value={"dispatchTime": "t"})
        ver.query_evr_telemetry = Mock(return_value=[{"ert": "t"}])
        ver.binary_file_verification()
        assert ver.entry["radiated"] is True
        assert ver.entry["verified"] is True
