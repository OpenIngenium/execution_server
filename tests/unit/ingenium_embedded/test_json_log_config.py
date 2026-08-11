"""Unit tests for ``ingenium_embedded.json_log_config.CustomJSONLog``."""

import json
import logging

from ingenium_embedded.json_log_config import CustomJSONLog


def _record(msg="hello", **attrs):
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg=msg, args=(), exc_info=None,
    )
    for key, value in attrs.items():
        setattr(record, key, value)
    return record


class TestCustomJSONLog:
    def test_basic_fields(self):
        formatter = CustomJSONLog()
        out = json.loads(formatter.format(_record("hi")))
        assert out["level"] == "INFO"
        assert out["message"] == "hi"
        assert out["service"] == "EMBEDDED_CODE"
        assert "timestamp" in out

    def test_event_and_data_included(self):
        formatter = CustomJSONLog()
        out = json.loads(formatter.format(_record(event="MY_EVENT", data={"k": "v"})))
        assert out["event"] == "MY_EVENT"
        assert out["data"] == {"k": "v"}

    def test_exc_info_adds_details_when_no_data(self):
        formatter = CustomJSONLog()
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            record = _record("err")
            record.exc_info = sys.exc_info()
        out = json.loads(formatter.format(record))
        assert "data" in out
        assert isinstance(out["data"]["details"], list)

    def test_exc_text_used_when_no_exc_info(self):
        formatter = CustomJSONLog()
        record = _record("err")
        record.exc_text = "cached traceback text"
        out = json.loads(formatter.format(record))
        assert out["data"]["details"] == ["cached traceback text"]

    def test_format_exception_none_returns_empty(self):
        assert CustomJSONLog.format_exception(None) == ""

    def test_exc_appended_to_existing_details_list(self):
        formatter = CustomJSONLog()
        import sys

        try:
            raise KeyError("x")
        except KeyError:
            record = _record("e", data={"details": ["existing"]})
            record.exc_info = sys.exc_info()
        out = json.loads(formatter.format(record))
        assert out["data"]["details"][0] == "existing"
        assert len(out["data"]["details"]) == 2
