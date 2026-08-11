"""Unit tests for ``ingenium_embedded.ingenium_library.validate_times``.

Pure time-window business logic: reference-time translation, SCET/ERT/SCLK
handling, and duration / timeout / lookback computation.
"""

import pytest

from ingenium_embedded import ingenium_library as ing_lib
from ingenium_embedded import ingenium_config as ic
from ingenium_embedded.ingenium_library import validate_times, StepExecutionError


class TestValidateTimesValidation:
    def test_unrecognized_step_type(self):
        with pytest.raises(StepExecutionError):
            validate_times({"start_time": "2020-04-09T01:02:03"}, "NOPE")

    def test_no_start_or_end(self):
        with pytest.raises(StepExecutionError):
            validate_times({}, "QUERY_EVR")


class TestValidateTimesErt:
    def test_start_time_ert(self):
        _, _, start, end = validate_times(
            {"start_time": "2020-04-09T01:02:03", "time_type": "ERT"}, "QUERY_EVR"
        )
        assert start == "2020-100T01:02:03"
        assert end is None

    def test_start_time_unparseable_ert(self):
        with pytest.raises(StepExecutionError):
            validate_times({"start_time": "bad", "time_type": "ERT"}, "QUERY_EVR")

    def test_end_time_ert(self):
        _, _, start, end = validate_times(
            {"end_time": "2020-04-09T01:02:03", "time_type": "ERT"}, "QUERY_EVR"
        )
        assert end == "2020-100T01:02:03"

    def test_end_time_unparseable_ert(self):
        with pytest.raises(StepExecutionError):
            validate_times({"end_time": "bad", "time_type": "ERT"}, "QUERY_EVR")


class TestValidateTimesSclk:
    def test_start_time_sclk(self):
        _, _, start, end = validate_times(
            {"start_time": "100", "time_type": "SCLK"}, "QUERY_EVR"
        )
        assert start == "100"

    def test_start_time_sclk_non_int(self):
        with pytest.raises(StepExecutionError):
            validate_times({"start_time": "abc", "time_type": "SCLK"}, "QUERY_EVR")

    def test_end_time_sclk_non_int(self):
        with pytest.raises(StepExecutionError):
            validate_times({"end_time": "abc", "time_type": "SCLK"}, "QUERY_EVR")


class TestValidateTimesReference:
    def test_reference_time_with_ert(self):
        ic.time_references["LAST_STEP_START"] = "2020-04-09T01:02:03.000Z"
        translated, _, start, _ = validate_times(
            {"start_time": "LAST_STEP_START", "time_type": "ERT"}, "QUERY_EVR"
        )
        assert translated == "2020-04-09T01:02:03.000Z"
        assert start == "2020-100T01:02:03"

    def test_reference_time_with_non_ert_raises(self):
        ic.time_references["LAST_STEP_START"] = "2020-04-09T01:02:03.000Z"
        with pytest.raises(StepExecutionError):
            validate_times({"start_time": "LAST_STEP_START", "time_type": "SCLK"}, "QUERY_EVR")

    def test_end_reference_time_with_non_ert_raises(self):
        ic.time_references["LAST_STEP_END"] = "2020-04-09T01:02:03.000Z"
        with pytest.raises(StepExecutionError):
            validate_times({"end_time": "LAST_STEP_END", "time_type": "SCLK"}, "QUERY_EVR")


class TestValidateTimesDuration:
    def test_duration_with_both_start_and_end_raises(self):
        with pytest.raises(StepExecutionError):
            validate_times(
                {"start_time": "2020-04-09T01:02:03", "end_time": "2020-04-09T01:03:03",
                 "duration": "10", "time_type": "ERT"}, "QUERY_EVR"
            )

    def test_duration_not_a_number(self):
        with pytest.raises(StepExecutionError):
            validate_times({"start_time": "100", "duration": "abc", "time_type": "SCLK"}, "QUERY_EVR")

    def test_duration_from_start_ert(self):
        _, _, start, end = validate_times(
            {"start_time": "2020-04-09T01:02:03", "duration": "60", "time_type": "ERT"}, "QUERY_EVR"
        )
        assert start == "2020-100T01:02:03"
        assert end == "2020-100T01:03:03"

    def test_duration_from_start_sclk(self):
        _, _, start, end = validate_times(
            {"start_time": "100", "duration": "10", "time_type": "SCLK"}, "QUERY_EVR"
        )
        assert start == "100"
        assert end == "110.0"

    def test_duration_from_end_ert(self):
        _, _, start, end = validate_times(
            {"end_time": "2020-04-09T01:03:03", "duration": "60", "time_type": "ERT"}, "QUERY_EVR"
        )
        assert start == "2020-100T01:02:03"
        assert end == "2020-100T01:03:03"


class TestValidateTimesTimeout:
    def test_timeout_computes_end_ert(self):
        _, _, start, end = validate_times(
            {"start_time": "2020-04-09T01:02:03", "timeout": 60, "time_type": "ERT"}, "WAIT_EHA"
        )
        assert end == "2020-100T01:03:03"

    def test_timeout_computes_end_sclk(self):
        _, _, start, end = validate_times(
            {"start_time": "100", "timeout": 10, "time_type": "SCLK"}, "WAIT_EHA"
        )
        assert end == "110"

    def test_timeout_requires_start(self):
        with pytest.raises(StepExecutionError):
            validate_times({"end_time": "2020-04-09T01:02:03", "timeout": 60, "time_type": "ERT"}, "WAIT_EHA")

    def test_timeout_with_end_raises(self):
        with pytest.raises(StepExecutionError):
            validate_times(
                {"start_time": "2020-04-09T01:02:03", "end_time": "2020-04-09T01:04:03",
                 "timeout": 60, "time_type": "ERT"}, "WAIT_EHA"
            )

    def test_timeout_ignored_when_not_included(self):
        # QUERY_EVR does not include timeout in the window computation.
        _, _, start, end = validate_times(
            {"start_time": "2020-04-09T01:02:03", "timeout": 60, "time_type": "ERT"}, "QUERY_EVR"
        )
        assert end is None


class TestValidateTimesLookback:
    def test_lookback_ert(self):
        _, _, start, _ = validate_times(
            {"start_time": "2020-04-09T01:02:03", "lookback": 3, "time_type": "ERT"}, "QUERY_EVR"
        )
        assert start == "2020-100T01:02:00"

    def test_lookback_sclk(self):
        _, _, start, _ = validate_times(
            {"start_time": "100", "lookback": 10, "time_type": "SCLK"}, "QUERY_EVR"
        )
        assert start == "90"
