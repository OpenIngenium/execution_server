# Testing

## Framework & configuration

- **Framework**: `pytest` + `pytest-cov` + `pytest-mock` (`requirements-dev.txt`).
- **Config**: `[tool.pytest.ini_options]` in `pyproject.toml`:
  - `testpaths = ["tests/unit"]`
  - `pythonpath = ["image"]` — makes `import ingenium_embedded` / `import
    execution_server` / `import state_manager` work without installing the
    package.
  - `python_files/classes/functions` — standard `test_*`/`Test*`/`test_*`
    discovery.
  - `addopts` always runs with coverage: `--cov=ingenium_embedded
    --cov-report=term-missing --cov-report=html --cov-report=xml`.
  - `filterwarnings = ["ignore::DeprecationWarning"]`.
  - **No `--cov-fail-under`** — intentional, per the comment in
    `pyproject.toml`: coverage is reported, not gated, because large legacy
    modules and integration-scope I/O paths aren't unit-tested yet.
  - `[tool.coverage.run]` scopes coverage to `source = ["ingenium_embedded"]`
    with `branch = true`; `execution_server.py`/`state_manager.py` are
    exercised by tests but not included in the coverage denominator.

Verified by running the suite directly in this repository: **558 tests
pass**, with **85% overall line coverage** of `ingenium_embedded` (branch
coverage enabled). Re-run `pytest` to reproduce these numbers as the code
evolves — treat any number in prose documentation (including this page) as a
snapshot, not a guarantee.

## Structure

`tests/unit/` mirrors `image/ingenium_embedded/` file-for-file:

```text
tests/unit/
├── conftest.py                       # global autouse fixtures
├── mocks/
│   ├── mock_redis.py                 # FakeRedis + make_redis_mock()
│   ├── mock_http_client.py           # make_response()/make_requests_mock()
│   └── test_helpers.py               # make_step() step-envelope factory
├── test_execution_server.py          # execution_server.py (handler-adjacent pure logic only)
└── ingenium_embedded/
    ├── test_cmd_step.py              # ↔ image/ingenium_embedded/cmd_step.py
    ├── test_wait_evr_step.py         # ↔ image/ingenium_embedded/wait_evr_step.py
    ├── test_token_auth.py            # ↔ JWT decode/refresh functions in ingenium_library.py
    ├── test_ingenium_library.py, test_ingenium_library_extra.py,
    │   test_ingenium_library_wrappers.py   # ↔ ingenium_library.py (split across 3 files, no 1:1 module match)
    └── ... one test_<module>.py per remaining step/library module
```

## Fixtures (`tests/unit/conftest.py`)

Two **autouse** fixtures apply to every test in the suite:

- **`reset_ingenium_config`** — snapshots (`copy.deepcopy`) a fixed list of
  mutable `ingenium_config` attributes before each test (`username`,
  `variables`, `manual_input_variables`, `ing_token`, `venue_token`,
  `run_mode`, `time_references`, `execution_id`, etc.), forces
  `ic.run_mode = 'SYNC'` for the duration of the test (so the `ing_execution`
  decorator doesn't try to report intermediate ASYNC results over a mocked-
  away HTTP client), then restores the snapshot afterward. This exists
  because `ingenium_config` is process-global mutable state — see
  [Core Components](Core-components.md#imageingenium_embeddedingenium_configpy-ic).
- **`mock_redis_client`** — replaces `ingenium_library.redis_client` with a
  bare `unittest.mock.MagicMock` via `monkeypatch`, so the `ing_execution`
  decorator's Redis caching calls never touch a real connection.

Non-autouse fixtures:
- **`make_step`** — exposes `mocks.test_helpers.make_step` as a fixture.

## Mocks (`tests/unit/mocks/`)

- **`FakeRedis`** (`mock_redis.py`) — minimal in-memory double implementing
  the subset of the `redis.StrictRedis` API the source actually calls:
  `get`/`set(..., ex=...)`/`delete`/`exists`/`hset(..., mapping=...)`/`hget`/
  `hgetall`/`hmset`/`hmget` (the last returning byte-encoded values, mirroring
  real Redis, so `.decode('utf-8')` call sites behave identically in tests).
  `make_redis_mock()` wraps it in a `MagicMock(wraps=fake)` so tests can both
  assert on calls *and* get real get/set semantics.
- **`make_response(status_code, json_data, text)`** / **`make_requests_mock()`**
  (`mock_http_client.py`) — build `requests.Response`-shaped doubles and a
  full `requests`-module double with `get/post/patch/put/delete` all wired to
  a default response.
- **`make_step(step_type, user_input, **overrides)`** (`test_helpers.py`) —
  builds a minimal, valid `Step` envelope (`execution_id`, `elem_id`,
  `number`, `step_type`, `variable`, `execution_user_input`,
  `execution.meta_data.status/time_started`, `execution.results`), so
  individual tests only need to set the fields relevant to what they exercise.

## What is unit-tested vs. integration-scope

**Covered** (per the file list above and the 85% figure): every step
module's `run`/`run_dummy`, `verification_lib`'s `Verify` hierarchy and
`CommandBase`/`FSWVerify`/`HWVerify`, JWT decode/refresh (`test_token_auth.py`),
core pure-logic helpers in `execution_server.py` (`get_step_idx`,
`needs_approval`, `requires_manual_input`, `is_command_step`, `run_step`'s
dispatch logic, `get_pid`).

**Not unit-tested** (explicitly noted in `tests/unit/test_execution_server.py`'s
module docstring and `pyproject.toml`'s coverage comment) — integration-scope,
requiring real I/O or process orchestration:
- The Tornado `RequestHandler` classes themselves (`ExecutionHandler`,
  `RunHandler`, etc.) — HTTP-level behavior.
- `WorkerPool`/`WorkerProcess`'s actual `ProcessPoolExecutor` subprocess
  machinery.
- `run_execution`'s full AUTO-loop orchestration against a real Core service.
- `process_cs_files`/`upload_file_to_fileserver` (real `tarfile`/`boto3`/
  filesystem I/O).

There is no end-to-end (multi-service) test suite in this repository — the
retired `tests/test_ci_*.py` integration/demo tests are gone; only
`tests/unit/` remains.

## Running tests

```bash
pytest                                          # full suite, with coverage report
pytest tests/unit --no-cov                      # skip coverage for faster iteration
pytest tests/unit/ingenium_embedded/test_cmd_step.py -q
pytest -k "TestRunStep"                         # by test-class/function name substring
```

## Adding tests for a new step

Follow the existing per-module pattern: create
`tests/unit/ingenium_embedded/test_<new_step>.py`, build inputs with
`make_step(step_type="...", user_input={...})`, monkeypatch/mock the specific
`ingenium_library`/`verification_lib` calls your step makes (the
`mock_redis_client` and `reset_ingenium_config` fixtures apply automatically),
and assert on `step['execution']['results']` / `['meta_data']['status']`. See
[Extending the System](Extending.md) for a full worked example.
