"""Unit tests for the Redis-backed execution-state helpers in
``ingenium_library`` (``copy_execution_state`` and ``wait_execution_switch``)
plus ``CustomScriptResponse.update_outputs_with_results``.

Redis is a FakeRedis in-memory double, so no real connections are made.
"""

import json

import pytest

from ingenium_embedded import ingenium_library as ing_lib
from ingenium_embedded.ingenium_library import (
    copy_execution_state,
    wait_execution_switch,
    HASH_TEMPLATE,
    CustomScriptResponse,
)

from mocks.mock_redis import FakeRedis


@pytest.fixture
def fake_redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(ing_lib, "redis_client", fake)
    return fake


class TestCopyExecutionState:
    def test_copies_state_to_target(self, fake_redis):
        source_hash = HASH_TEMPLATE.format("1")
        fake_redis.hmset(source_hash, {
            "execution_id": "1",
            "ampcs_session_information": json.dumps([{"data_path": "A"}]),
            "variables": json.dumps({"a": 1}),
            "environment_step_variables": json.dumps({}),
            "manual_input_variables": json.dumps({}),
            "channel_variables": json.dumps({}),
            "cmd_variables": json.dumps({}),
            "last_step_status": "PASS",
            "time_references": json.dumps({"LAST_STEP_START": "t"}),
            "mil_1553_variables": json.dumps({}),
        })

        states = copy_execution_state("1", "2")
        state_map = {s["name"]: s["value"] for s in states}
        assert state_map["execution_id"] == "2"
        assert state_map["variables"] == {"a": 1}
        assert state_map["last_step_status"] == "PASS"
        # Target hash was written.
        target_hash = HASH_TEMPLATE.format("2")
        assert fake_redis.hget(target_hash, "execution_id") == "2"


class TestWaitExecutionSwitch:
    def test_zero_wait_returns_immediately(self, fake_redis):
        # A wait value of 0 skips the polling loop entirely.
        fake_redis.set(f"execution-switch-wait:1", "0")
        assert wait_execution_switch("1") is None


class TestUpdateOutputsWithResults:
    def test_updates_outputs_entries_and_status(self):
        step_input = {
            "script_name": "s",
            "outputs": [{"name": "o1"}],
            "output_array": {"outputs": [{"name": "arr1"}]},
            "entries": [
                {
                    "entry_outputs": [{"name": "e_o1"}],
                    "entry_output_array": {"outputs": [{"name": "e_arr1"}]},
                }
            ],
        }
        csr = CustomScriptResponse(step_input)

        status_info = {
            "custom_script_status": "PASS",
            "logfile_path": "/log",
            "custom_script_outputs": {
                "outputs": {"o1": "val1"},
                "output_array": [{"arr1": 10}, {"arr1": 20}],
                "output_summary": "done",
                "entries": [
                    {
                        "verification_status": "PASS",
                        "entry_outputs": {"e_o1": "eval1"},
                        "entry_output_array": [{"e_arr1": 1}, {"e_arr1": 2}],
                    }
                ],
            },
        }
        csr.update_outputs_with_results(status_info)
        result = csr.return_intermediate_response()

        assert result["custom_script_status"] == "PASS"
        assert result["output_summary"] == "done"
        assert result["outputs"][0]["value"] == "val1"
        assert result["output_array"]["outputs"][0]["values"] == [10, 20]
        entry = result["entries"][0]
        assert entry["verification_status"] == "PASS"
        assert entry["entry_outputs"][0]["value"] == "eval1"
        assert entry["entry_output_array"]["outputs"][0]["values"] == [1, 2]

    def test_unknown_output_names_are_ignored(self):
        step_input = {"script_name": "s", "outputs": [{"name": "known"}],
                      "output_array": {"outputs": []}, "entries": []}
        csr = CustomScriptResponse(step_input)
        csr.update_outputs_with_results({
            "custom_script_status": "PASS",
            "logfile_path": "/log",
            "custom_script_outputs": {"outputs": {"unknown": "x"}},
        })
        # Known output remains unchanged, no error raised for the unknown name.
        assert csr.return_intermediate_response()["outputs"][0]["value"] == ""
