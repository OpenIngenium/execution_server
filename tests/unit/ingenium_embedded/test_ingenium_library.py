"""Unit tests for ``ingenium_embedded.ingenium_library`` core helpers.

These cover the pure, in-process business logic plus the ``ing_execution``
decorator and the HTTP reporting helpers (with ``requests`` mocked). No real
network, Redis, or filesystem I/O occurs.
"""

from datetime import datetime

import pytest

from ingenium_embedded import ingenium_library as ing_lib
from ingenium_embedded import ingenium_config as ic
from ingenium_embedded.ingenium_library import (
    ErrorType,
    ErrorSource,
    StepExecutionError,
    convert_time,
    to_utc_str,
    get_now_utc,
    create_step_error,
    return_step_with_error,
    dict_digest,
    dict_digest_str,
    get_empty_str_by_default,
    get_empty_dict_by_default,
    get_empty_array_by_default,
    get_dict_value_default_none,
    get_dict_value,
    determine_cmd_failure,
    get_reference_time,
    get_telemetry_query_time,
    record_step_start_end_times,
    check_guard,
    ing_execution,
    report_step_results2,
)

from mocks.test_helpers import make_step
from mocks.mock_http_client import make_response


# ---------------------------------------------------------------------------
# convert_time
# ---------------------------------------------------------------------------
class TestConvertTime:
    def test_doy_with_microseconds(self):
        result = convert_time("2020-100T01:02:03.123456")
        assert result == datetime(2020, 4, 9, 1, 2, 3, 123456)

    def test_doy_without_microseconds(self):
        result = convert_time("2020-100T01:02:03")
        assert result == datetime(2020, 4, 9, 1, 2, 3)

    def test_iso_without_microseconds(self):
        result = convert_time("2020-04-09T01:02:03")
        assert result == datetime(2020, 4, 9, 1, 2, 3)

    def test_iso_with_z_microseconds(self):
        result = convert_time("2020-04-09T01:02:03.123456Z")
        assert result == datetime(2020, 4, 9, 1, 2, 3, 123456)

    def test_iso_with_microseconds_no_z(self):
        result = convert_time("2020-04-09T01:02:03.123456")
        assert result == datetime(2020, 4, 9, 1, 2, 3, 123456)

    def test_invalid_raises_step_execution_error(self):
        with pytest.raises(StepExecutionError) as exc_info:
            convert_time("not-a-time")
        assert exc_info.value.error_obj["error_type"] == ErrorType.USER_INPUT_ERROR.value


# ---------------------------------------------------------------------------
# time formatting
# ---------------------------------------------------------------------------
class TestTimeFormatting:
    def test_to_utc_str_truncates_to_milliseconds_and_appends_z(self):
        dt = datetime(2020, 1, 2, 3, 4, 5, 678912)
        assert to_utc_str(dt) == "2020-01-02T03:04:05.678Z"

    def test_get_now_utc_matches_expected_format(self, monkeypatch):
        fixed = datetime(2021, 6, 7, 8, 9, 10, 111222)

        class _FrozenDatetime(datetime):
            @classmethod
            def utcnow(cls):
                return fixed

        monkeypatch.setattr(ing_lib, "datetime", _FrozenDatetime)
        assert get_now_utc() == "2021-06-07T08:09:10.111Z"


# ---------------------------------------------------------------------------
# error object helpers
# ---------------------------------------------------------------------------
class TestErrorHelpers:
    def test_create_step_error_defaults(self):
        err = create_step_error()
        assert err["message"] == "Error in embedded code"
        assert err["details"] == []
        assert err["error_type"] == ErrorType.INGENIUM_SERVICE_ERROR.value
        assert err["error_source"] == ErrorSource.EMBEDDED_CODE.value
        assert err["http_code_at_source"] == 0

    def test_create_step_error_custom(self):
        err = create_step_error(
            message="boom",
            details=["a", "b"],
            error_type=ErrorType.USER_INPUT_ERROR.value,
            error_source=ErrorSource.VENUE_SERVICE.value,
            http_code_at_source=500,
        )
        assert err == {
            "message": "boom",
            "details": ["a", "b"],
            "error_type": ErrorType.USER_INPUT_ERROR.value,
            "error_source": ErrorSource.VENUE_SERVICE.value,
            "http_code_at_source": 500,
        }

    def test_return_step_with_error_sets_status_and_error(self):
        step = make_step()
        err = create_step_error(message="bad")
        result = return_step_with_error(step, err)
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"] == err

    def test_step_execution_error_stores_error_obj(self):
        err = {"message": "x"}
        exc = StepExecutionError("msg", err)
        assert str(exc) == "msg"
        assert exc.error_obj is err


# ---------------------------------------------------------------------------
# dict helpers
# ---------------------------------------------------------------------------
class TestDictHelpers:
    def test_dict_digest_extracts_requested_keys(self):
        source = {"a": 1, "b": 2, "c": 3}
        assert dict_digest(source, ["a", "c", "missing"]) == {
            "a": 1,
            "c": 3,
            "missing": None,
        }

    def test_dict_digest_str_formats_key_values(self):
        source = {"a": 1, "b": None}
        assert dict_digest_str(source, ["a", "b"]) == "a: 1 b: None"

    def test_get_empty_str_by_default_none(self):
        assert get_empty_str_by_default(None) == ""

    def test_get_empty_str_by_default_decodes_bytes(self):
        assert get_empty_str_by_default(b"hello") == "hello"

    def test_get_empty_dict_by_default_none(self):
        assert get_empty_dict_by_default(None) == {}

    def test_get_empty_dict_by_default_parses_json_bytes(self):
        assert get_empty_dict_by_default(b'{"x": 1}') == {"x": 1}

    def test_get_empty_array_by_default_none(self):
        assert get_empty_array_by_default(None) == []

    def test_get_empty_array_by_default_parses_json_bytes(self):
        assert get_empty_array_by_default(b"[1, 2]") == [1, 2]


class TestGetDictValue:
    def test_default_none_returns_none_for_whitespace(self):
        assert get_dict_value_default_none({"k": "   "}, "k") is None

    def test_default_none_returns_value_for_non_empty_string(self):
        assert get_dict_value_default_none({"k": "v"}, "k") == "v"

    def test_default_none_returns_non_string_value(self):
        assert get_dict_value_default_none({"k": 5}, "k") == 5

    def test_get_dict_value_returns_default_for_whitespace(self):
        assert get_dict_value({"k": "  "}, "k", "fallback") == "fallback"

    def test_get_dict_value_returns_value_for_non_empty(self):
        assert get_dict_value({"k": "v"}, "k", "fallback") == "v"

    def test_get_dict_value_returns_default_when_missing(self):
        assert get_dict_value({}, "k", "fallback") == "fallback"

    def test_get_dict_value_returns_non_string_value(self):
        assert get_dict_value({"k": 0}, "k", "fallback") == 0


# ---------------------------------------------------------------------------
# determine_cmd_failure
# ---------------------------------------------------------------------------
class TestDetermineCmdFailure:
    def test_verify_true_fails_when_not_verified(self):
        assert determine_cmd_failure("CMD", True, {"verified": False, "radiated": True}) is True

    def test_verify_true_fails_when_not_radiated(self):
        assert determine_cmd_failure("CMD", True, {"verified": True, "radiated": False}) is True

    def test_verify_true_passes_when_both_true(self):
        assert determine_cmd_failure("CMD", True, {"verified": True, "radiated": True}) is False

    def test_verify_false_only_checks_radiated(self):
        assert determine_cmd_failure("CMD", False, {"radiated": False}) is True
        assert determine_cmd_failure("CMD", False, {"radiated": True}) is False


# ---------------------------------------------------------------------------
# time references
# ---------------------------------------------------------------------------
class TestTimeReferences:
    def test_get_reference_time_current_step_start(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "get_now_utc", lambda: "NOW")
        assert get_reference_time("CURRENT_STEP_START") == "NOW"
        assert get_reference_time("CURRENT_TIME") == "NOW"

    def test_get_reference_time_reads_config(self):
        ic.time_references["LAST_STEP_START"] = "2020-01-01T00:00:00.000Z"
        assert get_reference_time("LAST_STEP_START") == "2020-01-01T00:00:00.000Z"

    def test_get_reference_time_unknown_returns_empty(self):
        assert get_reference_time("DOES_NOT_EXIST") == ""

    def test_record_step_start_end_times_cmd(self):
        record_step_start_end_times("CMD", "start", "end")
        assert ic.time_references["LAST_STEP_START"] == "start"
        assert ic.time_references["LAST_STEP_END"] == "end"
        assert ic.time_references["LAST_FSW_CMD_STEP_START"] == "start"
        assert ic.time_references["LAST_FSW_CMD_STEP_END"] == "end"

    def test_record_step_start_end_times_cmd_sse(self):
        record_step_start_end_times("CMD_SSE", "s", "e")
        assert ic.time_references["LAST_SSE_CMD_STEP_START"] == "s"
        assert ic.time_references["LAST_SSE_CMD_STEP_END"] == "e"

    def test_record_step_start_end_times_non_cmd_only_updates_generic(self):
        record_step_start_end_times("WAIT_STEP", "s", "e")
        assert ic.time_references["LAST_STEP_START"] == "s"
        assert ic.time_references["LAST_FSW_CMD_STEP_START"] != "s"


# ---------------------------------------------------------------------------
# get_telemetry_query_time
# ---------------------------------------------------------------------------
class TestGetTelemetryQueryTime:
    def test_with_explicit_time_input(self):
        start, end = get_telemetry_query_time(60, "2020-04-09T01:02:03.000Z")
        assert start == "2020-100T01:02:03"
        assert end == "2020-100T01:03:03"

    def test_without_time_input_uses_now(self, monkeypatch):
        fixed = datetime(2020, 4, 9, 1, 2, 3)

        class _FrozenDatetime(datetime):
            @classmethod
            def utcnow(cls):
                return fixed

        monkeypatch.setattr(ing_lib, "datetime", _FrozenDatetime)
        start, end = get_telemetry_query_time(120)
        assert start == "2020-100T01:02:03"
        assert end == "2020-100T01:04:03"


# ---------------------------------------------------------------------------
# check_guard
# ---------------------------------------------------------------------------
class TestCheckGuard:
    def test_no_guard_passes(self):
        step = make_step()
        assert check_guard(step) is True

    def test_empty_guard_passes(self):
        step = make_step(guard="   ")
        assert check_guard(step) is True

    def test_present_guard_currently_passes(self):
        # Guard evaluation is a no-op stub that always passes; document behavior.
        step = make_step(guard="x > 1")
        assert check_guard(step) is True


# ---------------------------------------------------------------------------
# ing_execution decorator
# ---------------------------------------------------------------------------
class TestIngExecutionDecorator:
    def test_happy_path_returns_output_and_records_variable(self):
        @ing_execution
        def run(step):
            step["execution"]["results"] = {"value": 42}
            step["execution"]["meta_data"]["status"] = "PASS"
            return step

        step = make_step(step_type="WAIT_STEP")
        step["variable"] = {"name": "myvar"}
        result = run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"
        # variable results are recorded in ingenium_config
        assert ic.variables["myvar"] == {"value": 42}
        # decorator stamps completion timestamps
        assert "time_completed" in result["execution"]["meta_data"]
        assert "time_updated" in result["execution"]["meta_data"]

    def test_run_failure_is_reraised(self):
        @ing_execution
        def run(step):
            raise ValueError("boom")

        step = make_step()
        with pytest.raises(ValueError):
            run(step)

    def test_skipped_guard_short_circuits(self, monkeypatch):
        # Force guard to fail by patching check_guard to return False.
        monkeypatch.setattr(ing_lib, "check_guard", lambda step: False)

        @ing_execution
        def run(step):  # pragma: no cover - should never run
            raise AssertionError("run should not be called when guard fails")

        step = make_step()
        result = run(step)
        assert result is step

    def test_async_mode_reports_results(self, monkeypatch):
        ic.run_mode = "ASYNC"
        calls = []
        monkeypatch.setattr(
            ing_lib, "report_step_results", lambda *a, **k: calls.append(a)
        )

        @ing_execution
        def run(step):
            step["execution"]["meta_data"]["status"] = "PASS"
            return step

        step = make_step()
        run(step)
        # Called at least once (start) and once at completion in finally.
        assert len(calls) >= 1


# ---------------------------------------------------------------------------
# report_step_results2 (HTTP mocked)
# ---------------------------------------------------------------------------
class TestReportStepResults2:
    def _patch_common(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "refresh_ingenium_token", lambda: None)
        monkeypatch.setattr(
            ing_lib, "get_ing_authorization_header", lambda: {"Authorization": "Bearer x"}
        )

    def test_success_returns_json(self, monkeypatch):
        self._patch_common(monkeypatch)
        response = make_response(200, json_data={"ok": True})
        monkeypatch.setattr(ing_lib.requests, "post", lambda *a, **k: response)

        step_execution = {"meta_data": {"status": "PASS"}}
        result = report_step_results2(1, "elem", step_execution, None)
        assert result == {"ok": True}
        assert "time_completed" in step_execution["meta_data"]

    def test_error_message_sets_error_dict_when_status_missing(self, monkeypatch):
        self._patch_common(monkeypatch)
        response = make_response(200, json_data={})
        captured = {}

        def fake_post(url, json=None, headers=None):
            captured["json"] = json
            return response

        monkeypatch.setattr(ing_lib.requests, "post", fake_post)

        step_execution = {"meta_data": {}}
        report_step_results2(1, "elem", step_execution, "something failed")
        assert captured["json"]["meta_data"]["status"] == "ERROR"
        assert captured["json"]["meta_data"]["error"]["message"] == "something failed"

    def test_non_200_returns_none(self, monkeypatch):
        self._patch_common(monkeypatch)
        response = make_response(500, text="server error")
        monkeypatch.setattr(ing_lib.requests, "post", lambda *a, **k: response)

        step_execution = {"meta_data": {"status": "PASS"}}
        result = report_step_results2(1, "elem", step_execution, None)
        assert result is None
