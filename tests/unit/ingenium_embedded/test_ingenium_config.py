"""Unit tests for ``ingenium_embedded.ingenium_config``.

Covers the ``get_list_from_env_var`` helper and the environment-variable-driven
module constants that are evaluated at import time.
"""

import importlib

import pytest

from ingenium_embedded import ingenium_config as ic


class TestGetListFromEnvVar:
    def test_returns_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("SOME_LIST", raising=False)
        assert ic.get_list_from_env_var("SOME_LIST", ":", ["d"]) == ["d"]

    def test_returns_default_when_blank(self, monkeypatch):
        monkeypatch.setenv("SOME_LIST", "   ")
        assert ic.get_list_from_env_var("SOME_LIST", ":", ["d"]) == ["d"]

    def test_splits_and_strips_values(self, monkeypatch):
        monkeypatch.setenv("SOME_LIST", " a : b :c ")
        assert ic.get_list_from_env_var("SOME_LIST", ":", []) == ["a", "b", "c"]

    def test_single_value(self, monkeypatch):
        monkeypatch.setenv("SOME_LIST", "only")
        assert ic.get_list_from_env_var("SOME_LIST", ":", []) == ["only"]


class TestModuleConstants:
    def test_standard_time_references_seeded_empty(self):
        for name in ic.standard_time_references:
            assert name in ic.time_references

    def test_query_trial_intervals(self):
        assert ic.query_trial_intervals == [1, 2, 4, 8, 16]
        assert ic.max_query_trials == 5

    def test_header_defaults(self):
        assert ic.header["Content-Type"] == "application/json"
        assert ic.header["Accept"] == "application/json"


class TestEnvDrivenReload:
    """The channel/EVR constants are derived from env vars at import time.

    Reloading the module under controlled env exercises both the default and
    override branches. The module is reloaded back to a clean state afterwards.
    """

    @pytest.fixture
    def reload_config(self):
        yield
        # Restore module to pristine (unset) environment state.
        importlib.reload(ic)

    def test_defaults_when_env_unset(self, monkeypatch, reload_config):
        for var in (
            "VERIFY_FSW_CHANNELS",
            "VERIFY_FSW_EVR",
            "VERIFY_HW_CHANNELS",
            "VERIFY_HW_EVR",
            "VERIFY_FILE_CHANNELS",
            "VERIFY_FILE_EVR",
            "VERIFY_EVR_MSG",
        ):
            monkeypatch.delenv(var, raising=False)
        reloaded = importlib.reload(ic)
        assert reloaded.fsw_channels == ["CMD-0027"]
        assert reloaded.fsw_evr_name == "CMD_SVC_EVR_VC1_CMD_DISPATCHED"
        assert reloaded.hw_channels == ["CMD-0024"]
        assert reloaded.binary_file_channels == []
        assert reloaded.verify_evr_msg is False

    def test_overrides_from_env(self, monkeypatch, reload_config):
        monkeypatch.setenv("VERIFY_FSW_CHANNELS", "A-1:A-2")
        monkeypatch.setenv("VERIFY_FSW_EVR", "MY_FSW_EVR")
        monkeypatch.setenv("VERIFY_HW_CHANNELS", "H-1")
        monkeypatch.setenv("VERIFY_EVR_MSG", "true")
        reloaded = importlib.reload(ic)
        assert reloaded.fsw_channels == ["A-1", "A-2"]
        assert reloaded.fsw_evr_name == "MY_FSW_EVR"
        assert reloaded.hw_channels == ["H-1"]
        assert reloaded.verify_evr_msg is True

    def test_empty_env_yields_empty_channel_list(self, monkeypatch, reload_config):
        monkeypatch.setenv("VERIFY_FSW_CHANNELS", "")
        reloaded = importlib.reload(ic)
        assert reloaded.fsw_channels == []
