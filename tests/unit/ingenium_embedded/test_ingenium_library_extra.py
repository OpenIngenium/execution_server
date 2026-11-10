"""Additional unit tests for ``ingenium_embedded.ingenium_library``.

Covers URL builders, response formatting classes, the execution/step Redis cache
round-trips (via an in-memory FakeRedis), auth headers, session registration,
value/time parsing helpers, and the ``query_bus_1553`` / custom-script HTTP
wrappers (with ``requests`` mocked). No real network, Redis, or filesystem I/O.
"""

import pytest

from ingenium_embedded import ingenium_library as ing_lib
from ingenium_embedded import ingenium_config as ic
from ingenium_embedded.ingenium_library import (
    StepExecutionError,
    determine_response,
    get_session_information,
    register_session,
    get_authorization_header,
    get_ing_authorization_header,
    get_cs_files_authorization_header,
    get_timeout_with_margin5,
    determine_actual_value,
    record_channel_data,
    record_bus_1553_data,
    parse_int,
    parse_to_doy,
    query_bus_1553,
    get_script_status,
    halt_script,
    EhaResponse,
    EvrResponse,
    DpResponse,
    Bus1553Response,
    CustomScriptResponse,
)

from mocks.mock_redis import FakeRedis
from mocks.mock_http_client import make_response


# ---------------------------------------------------------------------------
# URL builders
# ---------------------------------------------------------------------------
class TestUrlBuilders:
    def setup_method(self):
        ic.venue_service_address = "http://vs"

    def test_eha_realtime(self):
        assert ing_lib.get_eha_realtime_url() == "http://vs/api/{}/eha/realtime".format(ic.venue_service_version)

    def test_various_builders(self):
        assert ing_lib.get_eha_realtime_multi_url().endswith("/eha/realtime_multi")
        assert ing_lib.get_evr_realtime_url().endswith("/evr/realtime")
        assert ing_lib.get_eha_chill_url().endswith("/eha/chill")
        assert ing_lib.get_evr_chill_url().endswith("/evr/chill")
        assert ing_lib.get_cmd_url().endswith("/cmd")
        assert ing_lib.get_mtak_url().endswith("/mtak")
        assert ing_lib.get_dp_url().endswith("/dp")
        assert ing_lib.get_query_1553_url().endswith("/bus1553")
        assert ing_lib.get_custom_script_start_url().endswith("/custom_script/start")
        assert ing_lib.get_custom_script_status_url().endswith("/custom_script")
        assert ing_lib.halt_custom_script_url().endswith("/custom_script")

    def test_test_endpoints(self):
        assert ing_lib.get_forced_errors().endswith("/test/forced_errors")
        assert ing_lib.get_test_eha().endswith("/test/eha")
        assert ing_lib.get_test_evr().endswith("/test/evr")
        assert ing_lib.get_test_dp().endswith("/test/dp")
        assert ing_lib.get_receipt_configs().endswith("/test/receipt_configs")
        assert ing_lib.get_scmf_config().endswith("/test/scmf_config")
        assert ing_lib.post_1553_test_data().endswith("/test/bus_1553")
        assert ing_lib.post_test_script_status().endswith("/test/custom_script_status")

    def test_venue_configurations_url_uses_env(self, monkeypatch):
        monkeypatch.setenv("VENUE_CONFIG_SERVER", "http://vc")
        assert ing_lib.get_venue_configurations_url() == "http://vc/api/{}/configurations".format(ic.venue_config_version)

    def test_custom_script_tar(self):
        assert ing_lib.get_custom_script_tar("logs/x.tar").endswith("logs/x.tar")


# ---------------------------------------------------------------------------
# determine_response (log-only branches)
# ---------------------------------------------------------------------------
class TestDetermineResponse:
    @pytest.mark.parametrize("code", [200, 400, 401, 403, 404, 408, 500])
    def test_status_codes_do_not_raise(self, code):
        # determine_response only logs; ensure every branch executes cleanly.
        assert determine_response("ep", make_response(code)) is None


# ---------------------------------------------------------------------------
# session registration
# ---------------------------------------------------------------------------
class TestSessions:
    def test_register_and_get_session(self):
        register_session("SIDE A", 100)
        assert get_session_information("SIDE A") == 100

    def test_register_updates_existing(self):
        register_session("SIDE A", 1)
        register_session("SIDE A", 2)
        assert get_session_information("SIDE A") == 2
        # only one entry for the data path
        matches = [e for e in ic.ampcs_session_information if e["data_path"] == "SIDE A"]
        assert len(matches) == 1

    def test_unknown_session_raises(self):
        with pytest.raises(Exception):
            get_session_information("UNKNOWN")


# ---------------------------------------------------------------------------
# auth headers
# ---------------------------------------------------------------------------
class TestHeaders:
    def test_venue_authorization_header(self):
        ic.venue_token = "vt"
        assert get_authorization_header()["Authorization"] == "Bearer vt"

    def test_ing_authorization_header(self):
        ic.ing_token = "it"
        assert get_ing_authorization_header()["Authorization"] == "Bearer it"

    def test_cs_files_header(self):
        ic.venue_token = "vt"
        header = get_cs_files_authorization_header()
        assert header["Authorization"] == "Bearer vt"
        assert header["Accept"] == "application/x-tar"


# ---------------------------------------------------------------------------
# misc helpers
# ---------------------------------------------------------------------------
class TestMiscHelpers:
    def test_timeout_with_margin(self):
        assert get_timeout_with_margin5(10) == 15

    def test_parse_int_integer_value(self):
        assert parse_int("5") == 5
        assert parse_int(5.0) == 5

    def test_parse_int_non_integer_raises(self):
        with pytest.raises(Exception):
            parse_int("5.5")

    def test_record_bus_1553_data(self):
        record_bus_1553_data({"bus_1553_var": "v1", "x": 1})
        assert ic.mil_1553_variables["v1"] == {"bus_1553_var": "v1", "x": 1}

    def test_record_channel_data_success(self):
        register_session("SIDE A", 55)
        record_channel_data({"channel_id": "C-1", "data_path": "SIDE A"})
        assert "55:C-1" in ic.channel_variables

    def test_record_channel_data_missing_fields(self):
        # No channel_id/data_path -> logs a warning, records nothing.
        record_channel_data({})
        assert ic.channel_variables == {}


# ---------------------------------------------------------------------------
# determine_actual_value
# ---------------------------------------------------------------------------
class TestDetermineActualValue:
    def test_eu_float(self):
        resp = {"dn_eu": "eu", "channelType": "FLOAT", "eu": "3.5"}
        out, vtype = determine_actual_value({"dn_eu": "EU"}, resp)
        assert out["actual_value"] == 3.5
        assert vtype == "FLOAT"

    def test_eu_status(self):
        resp = {"channelType": "STATUS", "channelStatus": "ON"}
        out, vtype = determine_actual_value({"dn_eu": "EU"}, resp)
        assert out["actual_value"] == "ON"
        assert vtype == "STRING"

    def test_eu_ascii_raises(self):
        resp = {"channelType": "ASCII"}
        with pytest.raises(StepExecutionError):
            determine_actual_value({"dn_eu": "EU"}, resp)

    def test_dn_float(self):
        resp = {"channelType": "FLOAT", "dn": "2.5"}
        out, vtype = determine_actual_value({"dn_eu": "DN"}, resp)
        assert out["actual_value"] == 2.5
        assert vtype == "FLOAT"

    def test_dn_integer(self):
        resp = {"channelType": "UNSIGNED_INT", "dn": "7"}
        out, vtype = determine_actual_value({"dn_eu": "DN"}, resp)
        assert out["actual_value"] == 7
        assert vtype == "INTEGER"

    def test_dn_ascii_string(self):
        resp = {"channelType": "ASCII", "dn": "text"}
        out, vtype = determine_actual_value({"dn_eu": "DN"}, resp)
        assert out["actual_value"] == "text"
        assert vtype == "STRING"


# ---------------------------------------------------------------------------
# parse_to_doy
# ---------------------------------------------------------------------------
class TestParseToDoy:
    def test_iso_format(self):
        assert parse_to_doy("2020-04-09T01:02:03") == "2020-100T01:02:03"

    def test_doy_format(self):
        assert parse_to_doy("2020-100T01:02:03") == "2020-100T01:02:03"

    def test_reference_time(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "get_reference_time", lambda name: "2020-04-09T01:02:03.000Z")
        assert parse_to_doy("LAST_STEP_START") == "2020-100T01:02:03"

    def test_invalid_raises(self):
        with pytest.raises(StepExecutionError):
            parse_to_doy("not-a-time")


# ---------------------------------------------------------------------------
# Redis cache round-trips (FakeRedis)
# ---------------------------------------------------------------------------
class TestExecutionCache:
    @pytest.fixture
    def fake_redis(self, monkeypatch):
        fake = FakeRedis()
        monkeypatch.setattr(ing_lib, "redis_client", fake)
        return fake

    def test_execution_cache_round_trip(self, fake_redis):
        ic.execution_id = "1"
        ic.venue_name = "venue-1"
        ic.variables = {"a": 1}
        ic.last_step_status = "PASS"
        ing_lib.store_execution_cache("1")

        # Mutate then restore from cache.
        ic.venue_name = "changed"
        ic.variables = {}
        ing_lib.reload_execution_cache("1")
        assert ic.venue_name == "venue-1"
        assert ic.variables == {"a": 1}

    def test_current_step_cache_round_trip(self, fake_redis):
        step = {"elem_id": "e1", "step_type": "WAIT_STEP", "number": "3"}
        ing_lib.store_current_step_cache("1", step)
        info = ing_lib.get_current_step_cache("1")
        assert info["current_step_id"] == "e1"
        assert info["current_step_type"] == "WAIT_STEP"
        assert info["current_step_number"] == "3"
        assert info["custom_script_session_id"] == ""

    def test_store_custom_script_session_id(self, fake_redis):
        ing_lib.store_custom_script_session_id("1", "rid-42")
        assert fake_redis.hget("execution_id:1", "custom_script_session_id") == "rid-42"


# ---------------------------------------------------------------------------
# Response formatting classes
# ---------------------------------------------------------------------------
class TestResponseClasses:
    def test_eha_response(self):
        obj = EhaResponse([{"channel_id": "C"}], "ts", "te", "s", "e")
        obj.update_eha_entry(0, {"dn": 5, "ert": "t"}, "C", "PASS", 5)
        out = obj.return_intermediate_response()
        assert out["entries"][0]["verification_status"] == "PASS"
        assert out["entries"][0]["dn"] == "5"

    def test_evr_response_exists(self):
        obj = EvrResponse([{"verification_condition": "EXISTS"}], "ts", "te", "s", "e")
        obj.update_evr_entry(0, [{"evrName": "E"}], 2)
        out = obj.return_intermediate_response()
        assert out["entries"][0]["verification_status"] == "PASS"
        assert out["entries"][0]["evr_data"][0]["evr_name"] == "E"

    def test_evr_response_does_not_exist(self):
        obj = EvrResponse([{"verification_condition": "DOES_NOT_EXIST"}], "ts", "te", "s", "e")
        obj.update_evr_entry(0, [], 0)
        assert obj.return_intermediate_response()["entries"][0]["verification_status"] == "PASS"

    def test_dp_response(self):
        obj = DpResponse([{"verification_condition": "GREATER_THAN", "verification_value": 0}], "ts", "te", "s", "e")
        obj.update_dp_entry(0, [{"apId": 1}], 3)
        out = obj.return_intermediate_response()
        assert out["entries"][0]["verification_status"] == "PASS"
        assert out["entries"][0]["products"][0]["apid"] == 1

    def test_bus_1553_response(self):
        obj = Bus1553Response([{"bus_1553_var": "v"}], "ts", "te", "s", "e")
        obj.update_bus_entry(0, {"rti": 2, "data_type": "INT"}, "v", "PASS", "42")
        out = obj.return_intermediate_response()
        assert out["entries"][0]["verification_status"] == "PASS"
        assert out["entries"][0]["rti"] == 2
        obj.update_entry_verification_status(0, "FAIL")
        assert out["entries"][0]["verification_status"] == "FAIL"

    def test_custom_script_response(self):
        step_input = {"script_name": "s", "outputs": [{"name": "o1"}], "entries": []}
        obj = CustomScriptResponse(step_input)
        assert obj.return_script_status() == "PENDING"
        obj.update_logfile_url("http://fs/log")
        assert obj.return_intermediate_response()["log_file_url"] == "http://fs/log"
        # outputs got a "value" field added
        assert obj.return_script_outputs()[0]["value"] == ""


# ---------------------------------------------------------------------------
# query_bus_1553 (HTTP mocked)
# ---------------------------------------------------------------------------
class TestQueryBus1553:
    def test_success(self, monkeypatch):
        ic.venue_service_address = "http://vs"
        monkeypatch.setattr(ing_lib.requests, "get", lambda *a, **k: make_response(200, json_data=[{"rti": 1}], text='[{"rti": 1}]'))
        result = query_bus_1553("s", "e", "v", 10, "SCLK")
        assert result == [{"rti": 1}]

    def test_non_200_raises(self, monkeypatch):
        ic.venue_service_address = "http://vs"
        monkeypatch.setattr(ing_lib.requests, "get", lambda *a, **k: make_response(500, json_data={"message": "boom"}))
        with pytest.raises(StepExecutionError):
            query_bus_1553("s", "e", "v", 10, "SCLK")

    def test_exception_raises(self, monkeypatch):
        ic.venue_service_address = "http://vs"
        monkeypatch.setattr(ing_lib.requests, "get", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("down")))
        with pytest.raises(StepExecutionError):
            query_bus_1553("s", "e", "v", 10, "SCLK")


# ---------------------------------------------------------------------------
# custom-script HTTP wrappers
# ---------------------------------------------------------------------------
class TestCustomScriptHttp:
    def test_get_script_status_builds_path(self, monkeypatch):
        ic.venue_service_address = "http://vs"
        captured = {}

        def fake_get(path, headers=None, verify=None, timeout=None):
            captured["path"] = path
            return make_response(200, json_data={})

        monkeypatch.setattr(ing_lib.requests, "get", fake_get)
        get_script_status("rid")
        assert captured["path"].endswith("/custom_script/rid")

    def test_halt_script_success(self, monkeypatch):
        ic.venue_service_address = "http://vs"
        monkeypatch.setattr(ing_lib.requests, "post", lambda *a, **k: make_response(204))
        assert halt_script("rid") == 204

    def test_halt_script_non_204_raises(self, monkeypatch):
        ic.venue_service_address = "http://vs"
        monkeypatch.setattr(ing_lib.requests, "post", lambda *a, **k: make_response(500, json_data={"message": "no"}))
        with pytest.raises(StepExecutionError):
            halt_script("rid")

    def test_halt_script_exception_raises(self, monkeypatch):
        ic.venue_service_address = "http://vs"
        monkeypatch.setattr(ing_lib.requests, "post", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("x")))
        with pytest.raises(StepExecutionError):
            halt_script("rid")
