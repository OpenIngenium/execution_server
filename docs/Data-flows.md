# Data Flows

Each flow below cites the real functions involved, in call order, in
`image/execution_server.py` and `image/ingenium_embedded/`.

## 1. Register an execution, then run one step (`SYNC`)

```text
PUT /api/v4/executions/{execution_id}   (VenueInfo body)
→ exec_api: verify JWT, check scopes
→ ExecutionHandler.put
→ StateManager.set_config_value(execution_id, "venue_service_address"|"venue_name"|"venue_id"|"venue_type"|"venue_sse", ...)
→ 204 No Content

POST /api/v4/executions/{execution_id}/run?run_mode=SYNC   (Step body)
→ exec_api: verify JWT, check scopes
→ RunHandler.post
→ mint a 1h venue-service JWT (jwt.encode(..., EXEC_VENUE_PRIVATE_PEM, "RS256"))
→ StateManager.set_config_value(execution_id, "venue_token"/"ing_token"/"run_mode")
→ WorkerPool.submit_func(run_execution, step, execution_id, elem_id, user_name, "SYNC")
→ [worker subprocess] run_execution(...) — step is not None branch
    → run_step(step)                      # dispatch by step['code']['name']
        → importlib.import_module("ingenium_embedded.<module>")
        → <module>.run(step)              # @ing_execution-wrapped
            → check_guard(step)
            → <step-specific venue/Core calls>
            → step['execution']['results'] = ...
            → step['execution']['meta_data']['status'] = "PASS"|"FAIL"|"ERROR"
→ [main process] yield fut                 # Tornado waits for the subprocess future
→ output_step['execution']['meta_data']['time_completed'] = get_now_utc()
→ 200 OK, body = output_step
```

If the worker raises, `RunHandler.post`'s `except` block tries to recover a
sensible step document (fetching it from Core by `elem_id` if none was
supplied), stamps `status='ERROR'` with the exception's traceback under
`meta_data.error`, and still returns `200` with that annotated step — the
HTTP layer itself only returns non-2xx for infrastructure-level failures
(e.g. failing to even *submit* to the worker pool, which returns `400`).

## 2. `ASYNC` / `AUTO` execution loop

```text
POST /api/v4/executions/{execution_id}/run?run_mode=ASYNC
→ RunHandler.post returns 202 immediately with the (unmodified) step body
→ [worker subprocess] run_execution(step=None, execution_id, elem_id, user_name, "ASYNC")
    → ingenium_library.reload_execution_cache(execution_id)
    → update_execution(execution_id, {"status": "RUNNING"})
    → get_execution(execution_id) -> execution (has "mode": "AUTO"|"MANUAL", pause_conditions, ...)
    → get_simple_elements(execution_id) -> flat list of procedure elements
    → get_next_step_idx(...) -> (idx, pause)
    → LOOP while not pause and idx is valid:
        → get_execution_step(execution_id, elem_id)
        → if elem_type == "PROCEDURE_SECTION": handle call/import/child-execution
             switch via switch_execution() + wait_execution_switch(), recurse into child elements
        → else: run_step(step) (same dispatch as flow #1)
             → report_step_results (start, via ing_execution, since run_mode == ASYNC)
             → <step executes>
             → report_step_results (end, via ing_execution)
        → get_execution(execution_id) again -> re-read mode/pause_conditions
             (a concurrent halt/pause request can change these mid-loop)
        → check pause_conditions: on_error / on_fail / on_break_point /
          on_section_end / on_procedure_end / on_manual_input / on_command
        → get_next_step_idx(..., idx+1, initial=False) -> advance
    → on loop exit (pause or elements exhausted):
        → if a parent_execution_id exists and idx == -1: resume the parent
          execution (suspend_resume_execution + switch_execution + continue
          the loop from the parent's next element)
        → update_execution(execution_id, {"status": "IDLE", "current_step_id": ...})
```

This is the mechanism behind procedure nesting: `PROCEDURE_SECTION` elements
either **import** (inline the referenced procedure's steps into the current
execution), or — if `callable` — **call** it as a **child execution**, switch
the claimed worker over to that child (`switch_execution` HTTP call +
in-process `WorkerPool.switch_execution`), run it to completion or a pause,
then resume the parent. `wait_execution_switch` (Redis-flag based, timeout
`EXECUTION_SWITCH_WAIT_SEC`, default 10s) exists to let a *different*
process (e.g. a UI-triggered action) know when the switch has propagated
before it starts issuing requests against the new `execution_id`.

## 3. EHA wait/verify polling loop (`WAIT_EHA` / `VERIFY_EHA`)

Shared by `wait_eha_step.run` (`wait=True`) and `verify_eha_step.run`
(`wait=False`) via `verification_lib.run_eha_verification`:

```text
Input: step['execution_user_input']['entries'] (list of {data_path, channel_id, verification_condition, ...})
→ validate_times(step_input, step_type) -> translated + display start/end times
→ group entries by data_path
→ EhaResponse(entries, ...) initializes step['execution']['results'] (so a
  halt/error mid-loop still returns a well-formed, if incomplete, response)
LOOP (at least once; continues while time remains AND entries still pending):
    → refresh_venue_tokens()
    → for each data_path: RealtimeEHAs(data_path, channel_ids, start_time, end_time, timeout, min_results=0)
        → for each entry whose channel now has a value:
            → determine_actual_value(entry, eha) -> (updated_eha, value_type)
            → Verify.factory(step, entry, value_type, eha_response=updated_eha).verify()
            → EhaResponse.update_eha_entry(index, eha, channel_id, verification_status, actual_value)
    → report_step_results(step, {"status": "RUNNING", ...}, None)   # intermediate progress, ALWAYS (not just ASYNC)
    → recompute "entries_pending":
        - wait=True  -> any entry NOT YET "PASS"
        - wait=False -> any entry still "PENDING" (never seen a value)
    → sleep(1) if time remains and entries still pending
POST-LOOP: any entry still "PENDING" is resolved by verification_condition
  (NOT_PRESENT -> PASS, everything else -> FAIL) and channel values are
  recorded via record_channel_data
→ step['execution']['meta_data']['status'] = "PASS" if every entry PASS else "FAIL"
```

The distinction between `wait` and `verify` is purely the pending-condition:
`VERIFY_EHA` is satisfied the moment every channel has reported *any* value
(pass or fail), while `WAIT_EHA` blocks until every channel's value actually
*passes* its condition (or the time window elapses).

## 4. Retry/backoff pattern for venue REST calls

Functions like `RealtimeEHA` (and, per the same structure observed in the
function bodies, the other `Chill*`/`Realtime*`/`Command*` venue-query
functions in `ingenium_library.py`) share one retry shape:

```text
for idx_query_trials in range(ic.max_query_trials + 1):     # max_query_trials = len(query_trial_intervals) = 5
    res = requests.get/post(path, ..., timeout=get_timeout_with_margin5(timeout))
    if res.status_code == 200: break
    if idx_query_trials >= ic.max_query_trials:
        raise StepExecutionError(...)                       # give up
    else:
        sleep(ic.query_trial_intervals[idx_query_trials])    # 1, 2, 4, 8, 16 seconds
```

`ic.query_trial_intervals = [2**i for i in range(5)]` — i.e. exponential
backoff capped at 5 attempts (cumulative wait ≈ 31s) before the call is
treated as a hard failure and surfaced as a `StepExecutionError` with
`ErrorType.QUERY_ERROR` / `ErrorSource.VENUE_SERVICE`.

## 5. `CUSTOM_SCRIPT` execution

```text
custom_script_step.run(step)
→ CustomScriptResponse(step_input)                       # wraps user input, tracks status/outputs
→ validate script_name / hash / script_path are present  # else return_step_with_error
→ start_custom_script(step_input) -> {"scriptRunId": ...}
→ store_custom_script_session_id(execution_id, scriptRunId)   # cached in Redis; read by HaltHandler
LOOP while elapsed < timeout and status == "PENDING":
    → refresh_venue_tokens()
    → get_script_status(scriptRunId) -> {custom_script_status, logfile_lines, logfile_url, ...}
    → CustomScriptResponse.update_outputs_with_results(...)
    → report_step_results(step, {"status": "RUNNING", "status_message": <joined log lines>}, None)
    → sleep(1)
→ store_custom_script_session_id(execution_id, '')        # release the halt-target cache
→ if logfile_url: process_cs_files(logfile_url, scriptRunId, custom_script_response)
    → downloads a .tar from the venue, extracts it, uploads members via
      upload_file_to_fileserver (boto3 -> MEDIA_BUCKET), returns a
      fileserver URL + parsed states (variables/channel_variables/
      manual_input_variables/mil_1553_variables) which are merged back into
      the corresponding ic.* dicts
→ if timed out or status not in {PASS, FAIL, ERROR}: halt_script(scriptRunId)
→ step['execution']['meta_data']['status'] = "PASS" if custom_script_status == "PASS" else "FAIL" (or "ERROR")
```

## 6. Halt a running step

```text
POST /api/v4/executions/{execution_id}/halt
→ HaltHandler.post
→ ic.ing_token = self.jwt_token                              # so any Core call below is authenticated
→ get_current_step_cache(execution_id)                       # cached by store_current_step_cache during ing_execution
→ if current step was CUSTOM_SCRIPT: reload_execution_cache; get_script_status;
    process_cs_files (best-effort, logged not raised on failure); halt_script
→ WorkerPool.cancel_run(execution_id)                         # SIGTERM/SIGKILL + pool rebuild
→ if a worker was found: report_step_results2(execution_id, current_step_id,
    {"meta_data": {"status": "FAIL"}, "results": {"log_file_url": ...}},
    "Step execution was canceled")
→ 202 Accepted (worker found) or 404 (nothing to cancel)
```

Note the explicit comment in the source: **`current_step_id` is deliberately
not advanced** on halt — the execution stays positioned on the step that was
canceled.

## 7. Command dispatch + verification (`CMD`, FSW/HW path)

```text
cmd_step.run(step)
→ for each entry in execution_user_input.entries:
    → report_step_results(step, {"status": "RUNNING", "status_message": "Dispatching command: ..."}, None)
    → if entry.verify:
        → FSWVerify(entry, data_path, step).fsw_command_verification()   (or HWVerify)
            → CommandBase.verify_command():
                → get_session_information(data_path)
                → query_eha_telemetry(channel_id, start, end)   # "before" snapshot
                → dispatch_cmd()                                # subclass-specific venue call
                → re-query EHA/EVR channels for the dispatch-confirmation
                  signal (ic.fsw_channels/fsw_evr_name or hw_channels/hw_evr_name)
                  within get_remaining_seconds()
      else:
        → CommandFSW(...) / CommandHW(...) directly (dispatch only, no post-verify)
    → determine_cmd_failure(step_type, verify, entry) -> stop early on first failure
→ step['execution']['meta_data']['status'] = "PASS" if every entry radiated/verified else "FAIL"
```

`ic.fsw_channels`/`ic.fsw_evr_name`/`ic.hw_channels`/`ic.hw_evr_name` (all
overridable via env vars, see [Configuration](Configuration.md)) define
*what telemetry proves a command was actually dispatched* — this is
mission-specific tuning baked into `ingenium_config.py`.
