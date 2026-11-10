"""Unit tests for the venue-service HTTP query/command wrappers in
``ingenium_embedded.ingenium_library``.

All wrappers share a contract: resolve a session from the data path, issue a
``requests`` call, raise ``StepExecutionError`` on a non-success status, and
return the parsed body on success. ``requests`` and ``time.sleep`` are mocked so
no real network calls or retry delays occur.
"""

import json

import pytest

from ingenium_embedded import ingenium_library as ing_lib
from ingenium_embedded import ingenium_config as ic
from ingenium_embedded.ingenium_library import (
    StepExecutionError,
    register_session,
    ChillEVRQuery,
    ChillEHAQuery,
    CommandFSW,
    CommandHW,
    CommandSCMF,
    CommandBinaryFile,
    CommandSSE,
    StartMTAK,
    ShutdownMTAK,
    DataProductsQuery,
    RealtimeEHA,
    RealtimeEHAs,
    RealtimeEVR,
)

from mocks.mock_http_client import make_response


@pytest.fixture(autouse=True)
def wrapper_env(monkeypatch):
    ic.venue_service_address = "http://vs"
    ic.venue_token = "vt"
    register_session("SIDE A", 5)
    # Avoid real retry sleeps in realtime queries.
    monkeypatch.setattr(ing_lib.time, "sleep", lambda s: None)


def _get(monkeypatch, response):
    monkeypatch.setattr(ing_lib.requests, "get", lambda *a, **k: response)


def _post(monkeypatch, response):
    monkeypatch.setattr(ing_lib.requests, "post", lambda *a, **k: response)


# ---------------------------------------------------------------------------
# Chill queries
# ---------------------------------------------------------------------------
class TestChillQueries:
    def test_chill_evr_success(self, monkeypatch):
        evrs = [{"evrName": "E", "evrMessage": "hello"}]
        _get(monkeypatch, make_response(200, text=json.dumps(evrs)))
        result = ChillEVRQuery("SIDE A", "ERT")
        assert result == evrs

    def test_chill_evr_message_filter(self, monkeypatch):
        evrs = [{"evrName": "E", "evrMessage": "hello"}, {"evrName": "F", "evrMessage": "bye"}]
        _get(monkeypatch, make_response(200, text=json.dumps(evrs)))
        result = ChillEVRQuery("SIDE A", "ERT", message_filter="hell")
        assert len(result) == 1

    def test_chill_evr_bad_evr_id(self, monkeypatch):
        _get(monkeypatch, make_response(200, text="[]"))
        with pytest.raises(StepExecutionError):
            ChillEVRQuery("SIDE A", "ERT", evr_id="not-int")

    def test_chill_evr_non_200(self, monkeypatch):
        _get(monkeypatch, make_response(500, json_data={"message": "boom"}))
        with pytest.raises(StepExecutionError):
            ChillEVRQuery("SIDE A", "ERT")

    def test_chill_evr_unknown_session(self, monkeypatch):
        with pytest.raises(StepExecutionError):
            ChillEVRQuery("UNKNOWN", "ERT")

    def test_chill_eha_success(self, monkeypatch):
        channels = [{"channelId": "C", "ert": "t"}]
        _get(monkeypatch, make_response(200, text=json.dumps(channels)))
        result = ChillEHAQuery("SIDE A", "ERT", channel_id="C")
        assert result == channels

    def test_chill_eha_non_200(self, monkeypatch):
        _get(monkeypatch, make_response(500, json_data={"message": "boom"}))
        with pytest.raises(StepExecutionError):
            ChillEHAQuery("SIDE A", "ERT")


# ---------------------------------------------------------------------------
# Command dispatch wrappers
# ---------------------------------------------------------------------------
class TestCommandWrappers:
    def test_command_fsw_success(self, monkeypatch):
        _post(monkeypatch, make_response(200, text='{"dispatchTime": "t"}'))
        assert CommandFSW("SIDE A", "cmd", "DEFAULT")["dispatchTime"] == "t"

    def test_command_fsw_non_200(self, monkeypatch):
        _post(monkeypatch, make_response(400, json_data={"message": "no"}))
        with pytest.raises(StepExecutionError):
            CommandFSW("SIDE A", "cmd", "DEFAULT")

    def test_command_fsw_unknown_session(self):
        with pytest.raises(StepExecutionError):
            CommandFSW("UNKNOWN", "cmd", "DEFAULT")

    def test_command_hw_success(self, monkeypatch):
        _post(monkeypatch, make_response(200, text='{"dispatchTime": "t"}'))
        assert CommandHW("SIDE A", "stem", "DEFAULT")["dispatchTime"] == "t"

    def test_command_hw_non_200(self, monkeypatch):
        _post(monkeypatch, make_response(400, json_data={"message": "no"}))
        with pytest.raises(StepExecutionError):
            CommandHW("SIDE A", "stem", "DEFAULT")

    def test_command_scmf_success(self, monkeypatch):
        _post(monkeypatch, make_response(200, text='{"dispatchTime": "t"}'))
        assert CommandSCMF("SIDE A", "/f.scmf")["dispatchTime"] == "t"

    def test_command_scmf_non_200(self, monkeypatch):
        _post(monkeypatch, make_response(400, json_data={"message": "no"}))
        with pytest.raises(StepExecutionError):
            CommandSCMF("SIDE A", "/f.scmf")

    def test_command_binary_file_success(self, monkeypatch):
        _post(monkeypatch, make_response(200, text='{"dispatchTime": "t"}'))
        result = CommandBinaryFile("SIDE A", "/s", "/t", "0", True, "DEFAULT")
        assert result["dispatchTime"] == "t"

    def test_command_binary_file_non_200(self, monkeypatch):
        _post(monkeypatch, make_response(400, json_data={"message": "no"}))
        with pytest.raises(StepExecutionError):
            CommandBinaryFile("SIDE A", "/s", "/t", "0", True, "DEFAULT")

    def test_command_sse_success(self, monkeypatch):
        _post(monkeypatch, make_response(200, text='{"dispatchTime": "t"}'))
        assert CommandSSE("SIDE A", "cmd")["dispatchTime"] == "t"

    def test_command_sse_non_200(self, monkeypatch):
        _post(monkeypatch, make_response(400, json_data={"message": "no"}))
        with pytest.raises(StepExecutionError):
            CommandSSE("SIDE A", "cmd")


# ---------------------------------------------------------------------------
# MTAK
# ---------------------------------------------------------------------------
class TestMtak:
    def test_start_mtak_success(self, monkeypatch):
        _post(monkeypatch, make_response(200, text='{"startTime": "t"}'))
        assert StartMTAK([5], "AB")["startTime"] == "t"

    def test_start_mtak_requires_list(self):
        with pytest.raises(StepExecutionError):
            StartMTAK(5, "AB")

    def test_start_mtak_non_200(self, monkeypatch):
        _post(monkeypatch, make_response(500, json_data={"message": "no"}))
        with pytest.raises(StepExecutionError):
            StartMTAK([5], "AB")

    def test_shutdown_mtak_success(self, monkeypatch):
        _post(monkeypatch, make_response(204))
        assert ShutdownMTAK() == "MTAK successfully shutdown"

    def test_shutdown_mtak_non_204(self, monkeypatch):
        _post(monkeypatch, make_response(500, json_data={"message": "no"}))
        with pytest.raises(StepExecutionError):
            ShutdownMTAK()


# ---------------------------------------------------------------------------
# Data products & realtime queries
# ---------------------------------------------------------------------------
class TestDataAndRealtime:
    def test_data_products_success(self, monkeypatch):
        _get(monkeypatch, make_response(200, text='[{"apId": 1}]'))
        assert DataProductsQuery("SIDE A", ap_ids=1) == [{"apId": 1}]

    def test_data_products_timeout_408(self, monkeypatch):
        _get(monkeypatch, make_response(408, json_data={"message": "timeout"}))
        with pytest.raises(StepExecutionError):
            DataProductsQuery("SIDE A")

    def test_data_products_non_200(self, monkeypatch):
        _get(monkeypatch, make_response(500, json_data={"message": "no"}))
        with pytest.raises(StepExecutionError):
            DataProductsQuery("SIDE A")

    def test_realtime_eha_success_sorted(self, monkeypatch):
        rows = [{"ert": "2020-100T00:00:02"}, {"ert": "2020-100T00:00:01"}]
        _get(monkeypatch, make_response(200, text=json.dumps(rows)))
        result = RealtimeEHA("SIDE A", "C", "s", "e")
        assert result[0]["ert"] == "2020-100T00:00:01"

    def test_realtime_eha_non_200_retries_then_raises(self, monkeypatch):
        _get(monkeypatch, make_response(500, json_data={"message": "no"}))
        with pytest.raises(StepExecutionError):
            RealtimeEHA("SIDE A", "C", "s", "e")

    def test_realtime_evr_success(self, monkeypatch):
        rows = [{"evrName": "E", "ert": "2020-100T00:00:01"}]
        _get(monkeypatch, make_response(200, text=json.dumps(rows)))
        result = RealtimeEVR("SIDE A", "s", "e")
        assert result[0]["evrName"] == "E"

    def test_realtime_evr_non_200(self, monkeypatch):
        _get(monkeypatch, make_response(500, json_data={"message": "no"}))
        with pytest.raises(StepExecutionError):
            RealtimeEVR("SIDE A", "s", "e")

    def test_realtime_ehas_success_sorted(self, monkeypatch):
        rows = [{"ert": "2020-100T00:00:02"}, {"ert": "2020-100T00:00:01"}]
        _get(monkeypatch, make_response(200, text=json.dumps(rows)))
        result = RealtimeEHAs("SIDE A", ["C"], "s", "e", 10)
        assert result[0]["ert"] == "2020-100T00:00:01"

    def test_realtime_ehas_non_200(self, monkeypatch):
        _get(monkeypatch, make_response(500, json_data={"message": "no"}))
        with pytest.raises(StepExecutionError):
            RealtimeEHAs("SIDE A", ["C"], "s", "e", 10)

    def test_realtime_evr_unknown_session(self):
        with pytest.raises(StepExecutionError):
            RealtimeEVR("UNKNOWN", "s", "e")
