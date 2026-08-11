"""Unit tests for ``ingenium_library.CustomScriptInputs`` (input/output parsing)
and ``start_custom_script`` (with ``requests`` mocked)."""

import pytest

from ingenium_embedded import ingenium_library as ing_lib
from ingenium_embedded import ingenium_config as ic
from ingenium_embedded.ingenium_library import (
    CustomScriptInputs,
    start_custom_script,
    register_session,
    StepExecutionError,
)

from mocks.mock_http_client import make_response


def _inp(name, type, value=None, required="YES", **extra):
    d = {"name": name, "type": type, "value": value, "required": required}
    d.update(extra)
    return d


def _build(inputs=None, outputs=None, entries=None):
    return CustomScriptInputs({
        "inputs": inputs or [],
        "outputs": outputs or [],
        "entries": entries or [],
    })


class TestParseInputTypes:
    def test_int(self):
        obj = _build(inputs=[_inp("a", "INT", "5")])
        assert obj.input_json["inputs"]["a"] == 5

    def test_int_bad_raises(self):
        with pytest.raises(StepExecutionError):
            _build(inputs=[_inp("a", "INT", "x")])

    def test_float(self):
        obj = _build(inputs=[_inp("a", "FLOAT", "1.5")])
        assert obj.input_json["inputs"]["a"] == 1.5

    def test_float_bad_raises(self):
        with pytest.raises(StepExecutionError):
            _build(inputs=[_inp("a", "FLOAT", "x")])

    def test_string(self):
        obj = _build(inputs=[_inp("a", "STRING", "hi")])
        assert obj.input_json["inputs"]["a"] == "hi"

    def test_bool_explicit(self):
        obj = _build(inputs=[_inp("a", "BOOL", "true")])
        assert obj.input_json["inputs"]["a"] == "true"

    def test_bool_default_true(self):
        obj = _build(inputs=[_inp("a", "BOOL", None, default_value="TRUE")])
        assert obj.input_json["inputs"]["a"] == "true"

    def test_bool_default_false(self):
        obj = _build(inputs=[_inp("a", "BOOL", None, default_value=None)])
        assert obj.input_json["inputs"]["a"] == "false"

    def test_bool_invalid_raises(self):
        with pytest.raises(StepExecutionError):
            _build(inputs=[_inp("a", "BOOL", "maybe")])

    def test_required_missing_raises(self):
        with pytest.raises(StepExecutionError):
            _build(inputs=[_inp("a", "STRING", None, required="YES")])

    def test_optional_missing_is_empty(self):
        obj = _build(inputs=[_inp("a", "STRING", None, required="NO")])
        assert obj.input_json["inputs"]["a"] == ""

    def test_enum_found(self):
        obj = _build(inputs=[_inp("a", "ENUM", "ON", enumerations=[{"symbol": "ON"}, {"symbol": "OFF"}])])
        assert obj.input_json["inputs"]["a"] == "ON"

    def test_enum_not_found_raises(self):
        with pytest.raises(StepExecutionError):
            _build(inputs=[_inp("a", "ENUM", "BAD", enumerations=[{"symbol": "ON"}])])

    def test_time(self):
        obj = _build(inputs=[_inp("a", "TIME", "2020-04-09T01:02:03")])
        assert obj.input_json["inputs"]["a"] == "2020-100T01:02:03"

    def test_time_bad_raises(self):
        with pytest.raises(StepExecutionError):
            _build(inputs=[_inp("a", "TIME", "not-a-time")])

    def test_data_path(self):
        register_session("SIDE A", 9)
        obj = _build(inputs=[_inp("a", "DATA_PATH", "SIDE A")])
        assert obj.input_json["inputs"]["a"] == 9

    def test_data_path_unknown_raises(self):
        with pytest.raises(StepExecutionError):
            _build(inputs=[_inp("a", "DATA_PATH", "UNKNOWN")])


class TestOutputsAndEntries:
    def test_outputs_default_empty(self):
        obj = _build(outputs=[{"name": "o1"}, {"name": "o2"}])
        assert obj.output_json["outputs"] == {"o1": "", "o2": ""}

    def test_entries_parsed(self):
        entries = [{
            "entry_inputs": [_inp("x", "INT", "3")],
            "entry_outputs": [{"name": "eo"}],
        }]
        obj = _build(entries=entries)
        parsed_entry = obj.output_json["entries"][0]
        assert parsed_entry["verification_status"] == "PENDING"
        assert parsed_entry["entry_inputs"]["x"] == 3
        assert parsed_entry["entry_outputs"] == {"eo": ""}


class TestStartCustomScript:
    def setup_method(self):
        ic.venue_service_address = "http://vs"
        ic.venue_token = "vt"

    def _step_input(self):
        return {"script_name": "s", "script_path": "/p", "hash": "h",
                "inputs": [], "outputs": [], "entries": []}

    def test_success(self, monkeypatch):
        monkeypatch.setattr(ing_lib.requests, "post", lambda *a, **k: make_response(200, text='{"scriptRunId": "rid"}'))
        assert start_custom_script(self._step_input())["scriptRunId"] == "rid"

    def test_non_200_raises(self, monkeypatch):
        monkeypatch.setattr(ing_lib.requests, "post", lambda *a, **k: make_response(500, json_data={"message": "no"}))
        with pytest.raises(StepExecutionError):
            start_custom_script(self._step_input())
