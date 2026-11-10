# API / Public Interfaces

## REST API

Full schema source of truth: [`execution.yaml`](../execution.yaml) (Swagger
2.0, `basePath: /api/v4`). All routes are registered in
`ExecutionServer.__init__` (`image/execution_server.py`) with a regex path
matching `execution_id` as `[0-9a-zA-Z\-]+`.

| Method | Path | Handler | Required scopes | Purpose |
|---|---|---|---|---|
| `PUT` | `/api/v4/executions/{execution_id}` | `ExecutionHandler.put` | `execute:wsts`, `execute:testbed`, `execute:sit`, `execute:other` | Register an execution against a venue (`VenueInfo` body: `venue_id`, `name`, `ampcs_address`, `sse_address`, `type`). Stores these into Redis via `StateManager`. |
| `DELETE` | `/api/v4/executions/{execution_id}` | `ExecutionHandler.delete` | same | Deletes the execution's Redis hash (`StateManager.delete_execution`). |
| `POST` | `/api/v4/executions/{execution_id}/run` | `RunHandler.post` | same | Runs a step. Query params: `run_mode` (`SYNC`\|`ASYNC`, default `SYNC`), `elem_id` (used when no body `step` is given). Body: `Step` (optional). See [Data Flows](Data-flows.md). |
| `GET` | `/api/v4/executions/{execution_id}/config_value` | `ConfigHandler.get` | same | Reads a single config field (query param `parameter_name`) via `StateManager.get_config_value`, then `ast.literal_eval`s the stored string back into a Python value. |
| `GET` | `/api/v4/executions/{execution_id}/variable_value` | `VariableHandler.get` | same | Reads a manual-input variable by name (query param `variable_name`) via `StateManager.get_variable_value`. |
| `POST` | `/api/v4/executions/{execution_id}/copy_state` | `CopyStateHandler.post` | same | Copies cached execution state to `target_execution_id` (query param) via `ingenium_library.copy_execution_state`. |
| `POST` | `/api/v4/executions/{execution_id}/switch` | `SwitchHandler.post` | same | Reassigns a **busy** worker from `execution_id` to `target_execution_id` (query param) via `WorkerPool.switch_execution`. Used internally during procedure-section call/import (`run_execution`), and is itself called cross-process via the `EXECUTION_SERVER` base URL. |
| `POST` | `/api/v4/executions/{execution_id}/halt` | `HaltHandler.post` | same | Cancels the step currently running for this execution (`WorkerPool.cancel_run`); for an in-flight `CUSTOM_SCRIPT`, first fetches/retrieves its log file and calls `halt_script`. |
| `GET` | `/api/v4/logging` | `LoggingHandler.get` | `admin` | Returns `{"level": <current level name>}`. |
| `POST` | `/api/v4/logging` | `LoggingHandler.post` | `admin` | Body `{"level": "<DEBUG|INFO|WARNING|ERROR|CRITICAL>"}`; calls `logger.setLevel(...)` on the `Global` logger at runtime. |
| `GET` | `/api/v4/health` | `HealthHandler.get` | *(none)* | Always `200 {"status": "OK", "message": ""}`. No auth. |

### Error responses

Handlers that raise use a consistent shape (see e.g. `ExecutionHandler.put`'s
`except` block):

```json
{
  "message": "<str(exception)>",
  "details": ["<traceback text>"],
  "error_type": "INGENIUM_SERVICE_ERROR",
  "error_source": "EXECUTION_SERVICE",
  "http_code_at_source": 0
}
```

This matches `execution.yaml`'s `ErrorResponse` definition, though the
`error_type`/`error_source` enum values used at the HTTP-handler layer
(`INGENIUM_SERVICE_ERROR` / `EXECUTION_SERVICE`) are a *subset* of the fuller
`ErrorType`/`ErrorSource` enums used inside step execution — see
[Error Handling](Error-handling.md).

### The `Step` envelope

Every step body (request and response) is, per `execution.yaml`'s `Step`
definition (which extends `ProcedureElement`), shaped like:

```json
{
  "elem_id": "...",
  "elem_type": "STEP",
  "execution_id": "...",
  "number": "3.2",
  "title": "...",
  "step_type": "CMD",
  "executed": false,
  "code": {"name": "cmd_step.run", "commit": "Latest", "release": "Latest"},
  "variable": {"name": "my_var"},
  "guard": "",
  "execution_user_input": { "...step-type-specific input..." },
  "execution": {
    "meta_data": {
      "status": "RUNNING",
      "status_message": "...",
      "time_started": "...",
      "time_completed": "...",
      "test_conductor": "...",
      "error": { "...ErrorResponse-shaped..." }
    },
    "results": { "...step-type-specific output..." }
  }
}
```

- `code.name` drives dispatch — see [Step dispatch convention](#step-dispatch-convention) below.
- `execution.meta_data.status` is one of `PASS`, `FAIL`, `ERROR`, `RUNNING`,
  `SKIPPED` (observed across step modules; `execution.yaml` does not enum
  this field explicitly).
- `execution.results` shape is step-type specific; most step modules deep-copy
  `execution_user_input` and annotate each entry in place (e.g. adding
  `radiated`/`verified`/`actual_value`/`verification_status`).

## Step dispatch convention

`run_step(step)` (`image/execution_server.py`) requires `code.name` to be
exactly `"<module>.<function>"` (a single `.`); it raises otherwise. It then:

```python
full_module_name = f'ingenium_embedded.{module_name}'
step_module = importlib.import_module(full_module_name)
function_to_call = getattr(step_module, function_name)
return function_to_call(step)
```

In practice `function_name` is almost always `run` (see the catalog in
[Core Components](Core-components.md#step-modules--catalog)); a few
modules also expose `run_dummy`/`run_dummy_get_session_info` as alternate
entry points intended for direct invocation by test tooling rather than
through `code.name` (the `run_dummy` *branch inside* `run` is a separate,
more common mechanism — see below).

## The `run_dummy` fake-venue convention

Several step modules (`cmd_step`, `check_config_step`, `gds_manual_step`,
`get_config_step`, `graph_eha_step`, `list_data_products_step`,
`query_evr_step`, `update_config_step`, `verify_eha_step`, `wait_data_products_step`,
`wait_eha_step`, `wait_evr_step`, `wait_step`) start `run(step)` with:

```python
if ic.manual_input_variables.get("step_function_name") and \
   ic.manual_input_variables.get("step_function_name").get('actual_value') == "run_dummy":
    return run_dummy(step)
```

Setting the `manual_input_variables['step_function_name']` variable (via a
preceding `MANUAL_INPUT` step, or directly in test setup) redirects execution
to a canned `run_dummy(step)` implementation that fabricates a `PASS` result
without contacting the Venue Service. This is a **repository-internal test
harness convention**, not a documented public API — the repository does not
explain who sets this variable in a real procedure vs. in tests.

## Python interfaces step authors use

These are the symbols a new step module is expected to import from
`ingenium_library`/`verification_lib` (see actual usage in existing step
modules for the canonical pattern):

| Symbol | Module | Signature / role |
|---|---|---|
| `ing_execution` | `ingenium_library` | Decorator; wraps `run(step)` with guard-condition checking, timing, caching, and ASYNC progress reporting. **Required** on every step's public `run`. |
| `create_step_error(message, details, error_type, error_source, http_code_at_source)` | `ingenium_library` | Builds an `ErrorResponse`-shaped dict. |
| `return_step_with_error(step, error_obj)` | `ingenium_library` | Sets `status='ERROR'` + `meta_data.error`, returns `step`. The standard way to bail out of a `run()` early. |
| `StepExecutionError(message, error_obj)` | `ingenium_library` | Exception carrying a pre-built `error_obj`; raised by library functions (e.g. `refresh_venue_tokens`, `CommandFSW`) so callers can re-log/re-wrap without losing the original error payload. |
| `report_step_results(step, step_execution, error_msg)` / `report_step_results2(execution_id, elem_id, step_execution, error_msg)` | `ingenium_library` | POSTs an intermediate or final result to Core. Use for progress updates during long-running steps (polling loops). |
| `get_dict_value(dict_obj, key, default_value)` / `get_dict_value_default_none(dict_obj, key)` | `ingenium_library` | Whitespace-safe dict lookups (treat all-whitespace strings as absent). |
| `dict_digest(dict_input, keys)` / `dict_digest_str(...)` | `ingenium_library` | Build a small, log-safe subset of a step for log statements. |
| `ErrorType`, `ErrorSource`, `EventName` | `ingenium_library` | Enums — see [Error Handling](Error-handling.md) for the full member lists. |
| `Verify.factory(step, query, value_type, eha_response=None, environment_type=None)` | `verification_lib` | Returns the right verifier for a value type; call `.verify()` for `(query_result, actual_value, verification_status)`. |
| `run_eha_verification(step, wait)` | `verification_lib` | Full EHA query+verify+poll loop; reuse rather than reimplement for any new EHA-flavored step. |
| `validate_times(execution_input, step_type)` | `ingenium_library` | Resolves a step's time-window inputs (including named `LAST_*` references) into concrete start/end times. |

See [Extending the System](Extending.md) for a worked example of wiring
these together into a brand-new step module.
