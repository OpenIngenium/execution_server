"""Unit tests for ``ingenium_embedded.wait_step``.

Migrated from the legacy integration test ``tests/test_ci_wait.py``: assertion
based, with ``time.sleep`` and Core reporting mocked so no real waiting or HTTP
occurs.
"""

from datetime import datetime, timedelta

import pytest

from ingenium_embedded import wait_step
from ingenium_embedded import ingenium_config as ic

from mocks.test_helpers import make_step


@pytest.fixture(autouse=True)
def no_real_io(monkeypatch):
    """Prevent real sleeping and real Core reporting during wait execution."""
    monkeypatch.setattr(wait_step.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(wait_step, "report_step_results", lambda *a, **k: None)


def _future_iso(seconds=10):
    return datetime.strftime(
        datetime.utcnow() + timedelta(seconds=seconds), "%Y-%m-%dT%H:%M:%S"
    )


def _future_doy(seconds=10):
    return datetime.strftime(
        datetime.utcnow() + timedelta(seconds=seconds), "%Y-%jT%H:%M:%S"
    )


class TestWaitStepDuration:
    def test_integer_duration_passes(self):
        step = make_step("WAIT_STEP", {"wait_type": "DURATION", "time_value": "4"})
        result = wait_step.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"

    def test_float_duration_passes(self):
        step = make_step("WAIT_STEP", {"wait_type": "DURATION", "time_value": "4.3"})
        result = wait_step.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"

    def test_non_numeric_duration_errors(self):
        step = make_step("WAIT_STEP", {"wait_type": "DURATION", "time_value": "hello"})
        result = wait_step.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"

    def test_date_as_duration_errors(self):
        step = make_step(
            "WAIT_STEP", {"wait_type": "DURATION", "time_value": "2017-11-20T00:15:00"}
        )
        result = wait_step.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"

    def test_zero_duration_skips_loop(self):
        step = make_step("WAIT_STEP", {"wait_type": "DURATION", "time_value": "0"})
        result = wait_step.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"


class TestWaitStepUntil:
    def test_until_iso_format_passes(self):
        step = make_step("WAIT_STEP", {"wait_type": "UNTIL", "time_value": _future_iso()})
        result = wait_step.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"

    def test_until_doy_format_passes(self):
        step = make_step("WAIT_STEP", {"wait_type": "UNTIL", "time_value": _future_doy()})
        result = wait_step.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"

    def test_until_time_in_past_errors(self):
        step = make_step(
            "WAIT_STEP", {"wait_type": "UNTIL", "time_value": "2017-11-20T00:15:00"}
        )
        result = wait_step.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"

    def test_until_invalid_format_errors(self):
        step = make_step(
            "WAIT_STEP", {"wait_type": "UNTIL", "time_value": "2017-1120T00:15:00"}
        )
        result = wait_step.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"

    def test_until_integer_errors(self):
        step = make_step("WAIT_STEP", {"wait_type": "UNTIL", "time_value": "1234"})
        result = wait_step.run(step)
        assert result["execution"]["meta_data"]["status"] == "ERROR"


class TestWaitStepDummy:
    def test_run_dummy_dispatch(self):
        ic.variables["step_function_name"] = "run_dummy"
        step = make_step("WAIT_STEP", {"wait_type": "DURATION", "time_value": "4"})
        result = wait_step.run(step)
        assert result["execution"]["meta_data"]["status"] == "PASS"
        assert result["execution"]["results"]["wait_type"] == "DURATION"
