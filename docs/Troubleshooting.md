# Troubleshooting

Every entry below is derived from an explicit code comment, an explicit
README statement, or directly traceable code behavior (e.g. a library's
documented semantics such as `configparser.ConfigParser.read` silently
skipping missing files). None are speculative "common sense" guesses.

## Guard conditions never actually skip a step

`check_guard(step)` (`image/ingenium_embedded/ingenium_library.py`) contains:

```python
guard_passed = True
...
else:
    # evaluate guard
    # TODO: implement evaluation guard.
    # This will involve evaluate the guard expression against the current variables.
    # guard_passed = True
    if guard_passed:
        ...
```

`guard_passed` is hardcoded `True` and the actual expression-evaluation logic
is an unimplemented `TODO`. **If you set a non-empty `guard` on a step
expecting it to be conditionally `SKIPPED`, it will not be** — every step
with a guard currently logs `"Guard condition was met."` unconditionally and
proceeds to execute. This is a documented-by-comment gap in the
implementation, not a bug you introduced.

## Empty/unset `PUBLIC_PEM` → every authenticated request fails with 401

`exec_api` decodes inbound JWTs against `os.environ.get('PUBLIC_PEM', '')`.
If unset, `jwt.decode` fails for every request to every route except
`/health`, and the response body includes
`f'Invalid JWT token: {traceback.format_exc()}'`. This is the first thing to
check if *all* non-health requests return `401` — see
[Configuration](Configuration.md#jwt--authentication) and
[Security](Security.md#authentication).

## Empty/unset `EXEC_VENUE_PRIVATE_PEM` → every `/run` call fails

`RunHandler.post` always mints a venue-service JWT via
`jwt.encode(venue_token_dict, exec_venue_private_pem, algorithm='RS256')`
before submitting the step. With `EXEC_VENUE_PRIVATE_PEM` unset (empty
string default), signing fails, is caught by the handler's outer
`except Exception as ex:`, and is reported as an `INGENIUM_SERVICE_ERROR`
in the response — i.e. **no step can run at all**, even one that wouldn't
otherwise need to talk to the Venue Service (like `WAIT`).

## Running `execution_server.py` from the wrong working directory

The README explicitly instructs:
```bash
cd image
python execution_server.py
```
This matters because `config.read('config.ini')`
(`configparser.ConfigParser.read`) **does not raise** if the file isn't
found at that relative path — it silently reads nothing. If you instead run
`python image/execution_server.py` from the repository root, `config.ini`
won't be found (`image/config.ini` ≠ `./config.ini` from that CWD), and the
subsequent `config.get('logging', 'LOG_LEVEL')` call will raise
`configparser.NoSectionError` because the config object has no sections at
all. Always run from inside `image/` (or set `HTTP_PORT`/`LOG_LEVEL`/`DEV`/
`REDIS_HOST`/`REDIS_PORT` entirely via environment variables and ensure the
process's CWD contains `config.ini`).

## Redis-backed routes fail without a reachable Redis

Per the README: "Run the server locally (requires a reachable Redis, or
accept connection errors on Redis-backed routes)." `StateManager.__init__`
and `ingenium_library`'s module-level `redis_client` both connect eagerly
(`redis.StrictRedis(...)` does not itself probe the connection, but the
first `hset`/`hget` call will raise `redis.exceptions.ConnectionError` if
nothing is listening). `/health` is unaffected (it touches neither Redis nor
auth), so a healthy `/health` response does **not** imply Redis or the JWT
keys are correctly configured.

## Misconfigured `REDIS_PORT` / `NUMBER_OF_KERNELS_MIN` fail silently to a default

Both `ExecutionServer.__init__` (main process) and the `ingenium_library.py`
module-import block (worker subprocess) wrap `int(REDIS_PORT)` in a bare
`try/except`, logging a warning and falling back to `6379` on failure — the
process does **not** fail to start. Similarly, a non-integer
`NUMBER_OF_KERNELS_MIN` logs an info message and falls back to `5`. If Redis
connections are going to an unexpected port, or the worker pool is a
different size than you configured, check for a typo in these env vars
rather than assuming a startup failure would have caught it.

## `"No worker is available"` under concurrent load

`WorkerPool.submit_func` raises `Exception('No worker is available')`
immediately if every worker is busy (`is_idle()` false) — there is no
request queueing. If you see this (surfaced by `RunHandler.post` as a `400`
with that message in `details`), you are running more concurrent
in-flight executions than `NUMBER_OF_KERNELS_MIN` allows; increase it (see
[Configuration](Configuration.md#server--http)) or reduce concurrent
execution count.

## `venue_config_manual_step.py` has an open question in its own source

```python
# HK: does this need to set parameters in ingenium_config.py ?
```
The module author left this unresolved directly in the code. If a
`VENUE_CONFIG_MANUAL` step's results seem to not propagate into
`ingenium_config` state the way other config-related steps do, this is a
known, author-flagged open question — not a regression.

## `check_config_step.py` / `get_config_step.py` field lookups are flagged as needing a fix

Both contain the inline comment `# HK: need to fix this` at the point where
a venue-config element's name is matched/collected
(`check["config_elem_name"] == element["config_elem_name"]` in
`check_config_step.py`; the `elements_to_query.append(...)` loop in
`get_config_step.py`). No further detail is given in the repository about
what specifically needs fixing — treat unexpected matching behavior in these
two steps as a known, flagged-but-undescribed rough edge rather than
assuming the logic is fully validated.

## Step-level `variable` capture is acknowledged as test-oriented only

In `ing_execution`'s wrapper (`ingenium_library.py`):
```python
# set variable of the step execution results
# HK: I think this is used only for tests currently. To be revisited when we
# support execution level state variables.
if variable_name is not None:
    ...
```
If a step's `variable` field doesn't behave the way you'd expect for
execution-level state sharing outside of a test context, this comment
documents that the author considered this path provisional.

## Coverage/test count drift

[Testing](Testing.md) states 558 passing tests and 85% coverage as of
when this wiki was written, verified by running `pytest` in this
repository. Treat these as a snapshot — re-run `pytest` to get current
numbers; the repository does not gate coverage (`--cov-fail-under` is
intentionally unset in `pyproject.toml`), so coverage can silently drift
down as new code is added without CI failing.

## No documented recovery for a hung `AUTO`-mode execution beyond `/halt`

The repository provides `HaltHandler`/`WorkerPool.cancel_run` as the
mechanism to forcibly stop a running step/worker (see
[Data Flows § Halt](Data-flows.md#6-halt-a-running-step)), and
`WorkerProcess.reset()` as the mechanism to recover a broken subprocess. No
other automated recovery/resume mechanism for a stuck `AUTO`-mode execution
is documented or implemented in this repository.
