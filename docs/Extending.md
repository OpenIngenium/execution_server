# Extending the System

## Extension point: adding a new step type

Because `run_step()` (`image/execution_server.py`) dispatches purely by
dynamically importing `ingenium_embedded.<module>` and calling
`getattr(module, function)(step)` from `step['code']['name']`, **adding a new
step type requires no change to `execution_server.py`'s routing at all** —
only a new module under `image/ingenium_embedded/`. This is the primary,
code-verified extension point in this repository.

Steps, using the existing modules as templates (e.g.
`image/ingenium_embedded/wait_step.py` for a simple case,
`image/ingenium_embedded/cmd_step.py` for one that calls the venue and
verifies):

1. **Create `image/ingenium_embedded/<new>_step.py`.**
   ```python
   from . import ingenium_config as ic
   from . import ingenium_library as ing_lib
   from .ingenium_library import ing_execution, create_step_error, return_step_with_error, StepExecutionError
   from .logging_util import logger
   import copy

   @ing_execution
   def run(step):
       step_input = copy.deepcopy(step["execution_user_input"])

       # 1. Validate input; bail out early via return_step_with_error on bad input.
       if not step_input.get("some_required_field"):
           error_obj = create_step_error(
               message="some_required_field must be present",
               details=[],
               error_type=ing_lib.ErrorType.USER_INPUT_ERROR.value,
               error_source=ing_lib.ErrorSource.EMBEDDED_CODE.value,
               http_code_at_source=0,
           )
           logger.error(error_obj["message"], extra={
               "event": ing_lib.EventName.USER_INPUT_VALIDATION.value,
               "data": error_obj,
           })
           return return_step_with_error(step, error_obj)

       # 2. Do the work — call ingenium_library / verification_lib helpers,
       #    wrapping venue/Core calls in try/except StepExecutionError + except Exception
       #    exactly like the existing step modules (see Error Handling).

       # 3. Populate results and status.
       step["execution"]["results"] = {"...": "..."}
       step["execution"]["meta_data"]["status"] = "PASS"
       step["execution"]["meta_data"]["status_message"] = ""
       return step
   ```
2. **Decorate `run` with `@ing_execution`.** This is required — it is what
   provides guard-condition checking, `ASYNC` progress reporting, execution
   caching, and consistent `STEP_START`/`STEP_END`/`STEP_ERROR` logging (see
   [Core Components](Core-components.md#ing_execution-decorator--what-every-step-gets-for-free)).
3. **Reuse shared library code** rather than re-implementing patterns already
   in `ingenium_library`/`verification_lib` — e.g. use `Verify.factory` for
   any value comparison, `run_eha_verification` for anything EHA-shaped, the
   `create_step_error`/`return_step_with_error`/`StepExecutionError` trio for
   all error paths, and the query-retry pattern (`ic.query_trial_intervals`)
   for any new outbound venue call.
4. **Add the new `step_type` to `execution.yaml`'s `Step.step_type` enum**
   (and any new request/response fields to a new/updated definition) so the
   contract stays accurate — this repository treats `execution.yaml` as the
   API's source of truth for schemas (see [Repository Structure](Repository-structure.md)).
5. **Add tests** under `tests/unit/ingenium_embedded/test_<new>_step.py`
   mirroring an existing test file for a structurally similar step — see
   [Testing](Testing.md#adding-tests-for-a-new-step). At minimum, cover:
   a success path, a user-input-validation failure, and a
   venue/Core-call failure (mocking `requests`/`ingenium_library` functions
   as appropriate).
6. **If the step needs a `run_dummy` fallback** (for exercising it without a
   real Venue Service — see [API Reference](Api-reference.md#the-run_dummy-fake-venue-convention)),
   add the same `if ic.manual_input_variables.get("step_function_name")...`
   guard at the top of `run()` seen in `cmd_step.py`/`check_config_step.py`/etc.

## Extension point: adding a new REST route

1. Add a `RequestLogHandler` subclass in `image/execution_server.py`,
   following the pattern of the existing handlers (each HTTP method wrapped
   in `@exec_api(required_scopes=[...], event='...', description='...')`,
   body parsed with `tornado.escape.json_decode`, response written with
   `self.finish(json.dumps(...))`).
2. Register the route (path regex, handler class) in the `handlers` list
   inside `ExecutionServer.__init__`.
3. Add the corresponding `path`/`definitions` entries to `execution.yaml`.
4. Add tests. Note from [Testing](Testing.md): handler-level HTTP
   behavior is currently **not** unit-tested in this repository (only the
   pure-logic helpers around it are) — if you add handler tests, you would
   be establishing a new pattern, not following an existing one; consider
   using Tornado's `AsyncHTTPTestCase` if you do.

## Extension point: adding a new external integration

Follow the existing pattern for talking to an external service (Core, Venue
Service, Venue Configuration Service, S3): a base-URL environment variable
with a hardcoded fallback default (see [Configuration](Configuration.md)),
a thin `requests`-based client function in `ingenium_library.py`, and the
`refresh_*_token()` + `get_*_authorization_header()` calls before every
outbound request if the integration needs bearer-token auth.

## Contribution workflow

Per the root [`README.md`](../README.md):

1. Clone the repository and create a feature branch off `devel`.
2. Install dev dependencies (`pip install -r requirements-dev.txt`) and run
   `pytest` before pushing.
3. Open a pull request against `devel` or `main`; CI (`pytest` +
   `docker build`, see [CI/CD](Cicd.md)) runs automatically.

There is no `CONTRIBUTING.md` in this repository; the above is the complete
documented process. There is no linting/formatting gate to satisfy (none is
configured — see [Development](Development.md)), but keep new code
stylistically consistent with the module you're editing (existing code uses
plain 4-space-indented Python with the `create_step_error`/logging pattern
shown above almost universally).

## What NOT to change casually

- **`ingenium_config.py`'s existing attribute names.** They are read/written
  by name across dozens of modules and by `tests/unit/conftest.py`'s
  `_MUTABLE_CONFIG_ATTRS` snapshot list — renaming one silently breaks state
  restoration between tests without a test failure pointing at the rename.
- **`ErrorType`/`ErrorSource` enum values.** The source comments explicitly
  call out that `ErrorType` must stay in sync with the Core API's
  `error_type` enum — changing values (not just adding new ones) is a
  cross-service breaking change this repository cannot detect on its own.
- **The `HASH_TEMPLATE = 'execution_id:{}'` key format**, shared between
  `state_manager.StateManager` and `ingenium_library`'s module-level
  `redis_client` — changing it in one place without the other breaks the
  handoff described in [Architecture](Architecture.md).
