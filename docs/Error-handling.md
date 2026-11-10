# Error Handling

## The error vocabulary (`ingenium_library.py`)

Three enums form the controlled vocabulary used by every structured
error/log payload in `image/ingenium_embedded/`:

**`ErrorType`** — *what kind of failure*:
`USER_INPUT_ERROR`, `DISPATCH_ERROR`, `VERIFICATION_ERROR`,
`VENUE_SERVICE_ERROR`, `QUERY_ERROR`, `TIMEOUT`, `INGENIUM_SERVICE_ERROR`,
`CONFIGURATION_ERROR`, `REPORTING_ERROR`, `DATA_PATH_ERROR`,
`ELEMENT_NOT_FOUND`, `STEP_ERROR`, `CONDITION_EVALUATION_ERROR`,
`CANNOT_RELATE_DATA_PATH`, `VALUE_CONVERSION_ERROR`, `TIME_VALIDATION_ERROR`.
A comment in the source flags that this list **must stay in sync with the
`error_type` enum in the Core API spec** — i.e. it is a cross-service
contract, not a purely local concern.

**`ErrorSource`** — *which component/service is responsible*:
`EMBEDDED_CODE`, `VENUE_CONFIGURATION`, `VENUE_SERVICE`. (Note:
`execution.yaml`'s `ErrorResponse.error_source` enum additionally lists
`AMPCS`, `VENUE_SERVER`, `EXECUTION_KERNEL`, `EXECUTION_SERVER`, `OTHER` —
the HTTP-facing spec's vocabulary is a **superset** of the Python enum used
inside step code; the two are related but not identical.)

**`EventName`** — *what operation was being attempted* when a log/error was
recorded (~45 members), e.g. `DISPATCH_COMMAND_FSW`, `VERIFY_COMMAND`,
`QUERY_EHAS`, `QUERY_EVRS`, `TIME_VALIDATION`, `STEP_START`/`STEP_ERROR`/
`STEP_END`, `CUSTOM_SCRIPT_STATUS`, `REDIS_CHECK`, `GUARD_CONDITION_EVALUATION`,
etc. — see `image/ingenium_embedded/ingenium_library.py` for the full list.
This is the field to search/filter on in logs when tracing a specific kind of
operation across many step types.

## The error object shape

`create_step_error(message, details, error_type, error_source,
http_code_at_source)` (`ingenium_library.py`) builds the canonical dict used
everywhere a step needs to report a failure:

```python
{
    'message': message,
    'details': details,                    # list of strings, often [traceback.format_exc()]
    'error_type': error_type,               # an ErrorType(...).value
    'error_source': error_source,           # an ErrorSource(...).value
    'http_code_at_source': http_code_at_source,
}
```

This matches `execution.yaml`'s `ErrorResponse` schema field-for-field.

## Propagation pattern within a step

Every step module follows the same shape:

```text
try:
    <call a library/venue function>
except StepExecutionError as ex:
    # a library function already built a well-formed error_obj — reuse it
    logger.error(msg, extra={"event": ..., "data": {..., "details": [str(ex.error_obj)]}})
    return return_step_with_error(step, ex.error_obj)
except Exception as ex:
    # unexpected failure — build a fresh error_obj from the traceback
    error_obj = create_step_error(message=msg, details=[traceback.format_exc()], ...)
    logger.error(msg, extra={"event": ..., "data": error_obj})
    return return_step_with_error(step, error_obj)
```

`return_step_with_error(step, error_obj)` sets
`step['execution']['meta_data']['status'] = 'ERROR'` and
`step['execution']['meta_data']['error'] = error_obj`, then returns `step`
normally (i.e. **errors are returned, not raised**, from a step's `run()` in
the common case — this is why `run()` functions always "return step" even on
failure). `StepExecutionError` itself (raised by library functions like
`refresh_venue_tokens`, `CommandFSW`, `get_session_information`) is the one
exception type that carries a pre-built `error_obj`, letting callers avoid
re-deriving one from a bare traceback.

## Propagation at the `ing_execution` decorator layer

If a step's `run_function` raises **anything** (rather than returning a
`return_step_with_error`-annotated step), `ing_execution`'s wrapper logs a
`STEP_ERROR` event and **re-raises** (`raise` with no arguments, preserving
the original traceback) — it does not swallow it. That exception propagates
out of `run_step()`, out of `run_execution()` (which has an outer
`except:`/`try` in the `AUTO` loop path — see below), and, for the `SYNC`
single-step path, up to the `ProcessPoolExecutor` future, which
`RunHandler.post`'s `except Exception as ex:` block catches.

## Propagation at the HTTP layer

Every handler method body is wrapped in a broad `try/except` that builds the
same `ErrorResponse`-shaped dict described in
[API Reference](Api-reference.md#error-responses) and sets an HTTP status
— `400` for most handlers, `500` for `HaltHandler`, and (uniquely)
`RunHandler.post`, which **still returns `200`** with the step body annotated
`status: ERROR` whenever it can recover/fetch a step to annotate, only
falling back to `400` if it cannot even identify which step to report against.
This means **API consumers cannot rely on HTTP status code alone** to detect
step-level failure for `run` calls — they must inspect
`execution.meta_data.status` in the response body.

## Retries

Retries exist at exactly one layer: outbound Venue Service REST calls inside
`ingenium_library.py` (`RealtimeEHA` and the other `Chill*`/`Realtime*`/
`Command*` functions), using the exponential-backoff loop described in
[Data Flows § Retry/backoff pattern](Data-flows.md#4-retrybackoff-pattern-for-venue-rest-calls)
(`ic.query_trial_intervals = [1, 2, 4, 8, 16]` seconds, 5 attempts, then a
hard `StepExecutionError`). There is **no** retry logic for calls to Core
(`update_execution`, `get_execution`, `report_step_results`, etc.) — a
failed Core call returns `(None, error_msg)` (or `None`) once, with no
re-attempt, and callers propagate that as a step/execution error immediately.
There is also no retry around `WorkerPool.submit_func`'s
`BrokenProcessPool` handling — a broken pool is *repaired* (`reset()`) but
the specific submission that triggered the break is not automatically
retried; the caller receives an exception.

## Logging

- **Two loggers**: `'Global'` (main Tornado process, plain `StreamHandler`,
  used by `execution_server.py`/`state_manager.py`) and
  `ingenium_embedded`'s module logger (worker subprocess, JSON-formatted via
  `CustomJSONLog`, used by every file under `image/ingenium_embedded/`).
- **JSON log shape** (`json_log_config.CustomJSONLog.format`): always
  `timestamp`, `level`, `message`, `service: "EMBEDDED_CODE"`, `user_name`
  (from `ic.username`); conditionally `event` and `data` (whatever dict was
  passed as `extra={"data": ...}`, typically an error-object or a step
  digest); exception info is folded into `data.details` if present.
- **HTTP access logging**: `RequestLogHandler.finish()` logs every non-`GET`
  response (and every `GET` that isn't 2xx) via the `Global` logger, with
  `self.log_dict` (event name/description/user_name, set by `exec_api`) plus
  the parsed response body under `data` when the body is valid JSON.
- **Runtime log-level control**: `GET/POST /api/v4/logging` (admin scope)
  reads/sets the `Global` logger's level live — see
  [API Reference](Api-reference.md).

## User-facing errors

For HTTP clients, "user-facing" means the JSON `ErrorResponse` body described
above — there is no separate error-page/HTML rendering (the service is a pure
JSON API). For **manual steps** specifically (`manual_input_step`,
`manual_eip_step`, etc.), a bad user-supplied value (e.g. a non-numeric
string for an `INTEGER` field) becomes a `USER_INPUT_ERROR`
`StepExecutionError`, surfaced through the normal step-error path — i.e. a
human tester's typo is reported through exactly the same channel as a venue
outage, distinguished only by `error_type`/`error_source`.

## Recovery behavior

- **Worker-level**: `WorkerProcess.reset()` (SIGTERM → SIGKILL → rebuild)
  recovers from a broken/stuck subprocess; triggered automatically on
  `BrokenProcessPool` or any submit-time exception, and manually via
  `HaltHandler` → `WorkerPool.cancel_run`.
- **Token-level**: `refresh_venue_tokens`/`refresh_ingenium_token` recover
  from an expired-but-structurally-valid token by re-signing a fresh one
  with a new 30-minute (Ingenium) / the caller re-mints a 1-hour (venue,
  minted per-`run` call) expiry — see [Security](Security.md).
- **Execution-level**: `stop_execution_with_error(execution_id, msg)` posts
  an `ERROR`-level execution message to Core and marks the execution `IDLE`
  — used throughout `run_execution`'s `AUTO` loop whenever a Core call itself
  fails (as opposed to a step failing, which is reported per-step and simply
  ends the loop via the `on_error` pause condition).
- **No automatic execution-level retry**: once `run_execution`'s `AUTO` loop
  stops (pause condition, error, or exhausted elements), nothing in this
  repository automatically resumes it — resumption is caller-driven (a new
  `POST .../run` call).
