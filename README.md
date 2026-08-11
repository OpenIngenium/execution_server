# execution_server
Step execution service for ingenium.

This service uses a pool of Python worker processes to execute steps.


### API
REST API is defined in execution.yaml

### Environment Variables

All settings fall back to defaults in `image/config.ini`; the environment
variables below override them at runtime.

| Variable | Default (`config.ini`) | Purpose |
|----------|------------------------|---------|
| `REDIS_HOST` | `127.0.0.1` | Redis host used for the execution/step cache. |
| `REDIS_PORT` | `6379` | Redis port. |
| `HTTP_PORT` | `9999` | Port the Tornado server listens on. |
| `LOG_LEVEL` | `DEBUG` | Root log level. |
| `DEV` | `false` | When `true`, enables Tornado autoreload. |
| `NUMBER_OF_KERNELS_MIN` | `5` (code default) | Minimum worker-process pool size. |
| `PUBLIC_PEM` | _(empty)_ | RSA **public** key (PEM) used to verify inbound Ingenium JWTs (RS256). |
| `EXEC_VENUE_PRIVATE_PEM` | _(empty)_ | RSA **private** key (PEM) used to mint/refresh venue-service JWTs. |
| `EXEC_VENUE_PUBLIC_PEM` | _(empty)_ | RSA **public** key (PEM) used to verify venue-service JWTs. |

> **Note:** Authentication uses RS256 asymmetric keys (PyJWT 2.x). The legacy
> `JWT_SECRET` HMAC secret is **no longer used**.

### How to run in local Docker environment

1. Check out the following projects at the same directory level:

   * `Ingenium/execution_server`
   * `Ingenium/execution-dep`

2. Set environment variables if needed. The env variables are set in `docker-compose.yml`.

3. Build Docker images and run:

```bash
cd execution-dep/compose_single_node
sudo -E ./run_compose.sh up execution_server
```

### How to run standalone with Docker

```bash
# Build the image
docker build -t ingenium-exec-server .

# Run it (override env vars as needed)
docker run --rm -p 9999:9999 \
  -e REDIS_HOST=host.docker.internal \
  -e REDIS_PORT=6379 \
  -e PUBLIC_PEM="$(cat ingenium_public.pem)" \
  -e EXEC_VENUE_PRIVATE_PEM="$(cat venue_private.pem)" \
  -e EXEC_VENUE_PUBLIC_PEM="$(cat venue_public.pem)" \
  ingenium-exec-server
```

The server listens on port `9999` (see `EXPOSE` in the `Dockerfile`).

### How to run in Swarm Deployment
```bash
make
```

## Testing

This service uses **fast, isolated unit tests** (pytest) that run inside the
service. Every external collaborator (venue service, Core service, Redis, S3,
`datetime`, `time.sleep`) is mocked — tests perform no real network, Redis, or
filesystem I/O, and run deterministically in any order.

The legacy Python integration scripts (`tests/test_ci_*.py`) and demonstration
utilities have been **retired**; their business logic is now covered directly by
unit tests. Integration testing, where still required, is handled by the
external CI pipeline and is out of scope for this suite.

### Layout

```
tests/unit/
    conftest.py                 # sys.path setup, config-state reset, Redis mock
    mocks/
        test_helpers.py         # make_step() step-envelope factory
        mock_http_client.py     # make_response() / make_requests_mock()
        mock_redis.py           # FakeRedis + make_redis_mock()
    test_execution_server.py    # execution_server.py business-logic helpers
    ingenium_embedded/          # mirrors the production source tree
        test_*.py               # one file per source module
```

### Running the tests

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

# Run the full suite with coverage (configured in pyproject.toml)
pytest

# Iterate quickly without coverage
pytest tests/unit --no-cov
```

Runner configuration lives in `pyproject.toml` (`[tool.pytest.ini_options]`),
which sets `testpaths = ["tests/unit"]`, `pythonpath = ["image"]`, and coverage
of the `ingenium_embedded` package.

### Runtime

The service targets **Python 3.14** (see `Dockerfile` and `.python-version`,
which are kept in sync). The runtime and dependencies were upgraded from the
legacy Python 3.7.2 baseline; see the **Runtime & dependency upgrade** section
below.

### Coverage scope

The suite (500+ tests, ~85% line coverage) covers all first-party business logic
that can be exercised without a live venue/Core backend:

- **All step modules** (`ingenium_embedded/*_step.py`) — happy paths, input
  validation, error handling, and `run_dummy` fallbacks.
- **`verification_lib.py`** — the `Verify` factory and verifier subclasses,
  `type_check`, `verify_change`, EVR/data-product verification, the
  `run_eha_verification` orchestrator, and the FSW/HW/BinaryFile command
  verification state machine.
- **`ingenium_library.py`** — the `ing_execution` decorator, time/dict/error
  helpers, `validate_times`, response classes, the Redis execution/step cache,
  Core-service API wrappers, venue-service query/command wrappers, config
  get/update, custom-script input parsing, JWT token decode/refresh, and
  reporting.
- **`execution_server.py`** — the pure step-selection/pause/dispatch helpers
  (`get_step_idx`, `needs_approval`, `requires_manual_input`, `is_command_step`,
  `run_step`).
- **`ingenium_config.py`**, **`ingenium_step_sdk.py`**, **`json_log_config.py`**,
  **`logging_util.py`**.

Deliberately **not** unit-tested (integration-scope):

- `process_cs_files` / `upload_file_to_fileserver` — real tarfile extraction, S3
  (`boto3`) upload, and local filesystem I/O; these belong to integration tests.
- The Tornado request handlers, `ProcessPoolExecutor` worker machinery, and the
  `run_execution` Core-orchestration loop in `execution_server.py`.

`--cov-fail-under` in `pyproject.toml` is intentionally left unset (reporting
only) because of the excluded I/O paths above; raise it toward 100% once those
are covered under the production runtime.

### Notable fix

A latent defect was fixed in `image/ingenium_embedded/gds_manual_step.py`: the
generic `except` handlers for `ShutdownMTAK`/`StartMTAK` referenced
`ErrorType.VENUE_SERVICE` and `ErrorSource.VENUE_SERVICE_ERROR` (neither exists),
so any non-`StepExecutionError` failure crashed the handler with an
`AttributeError` instead of returning a clean error step. Regression tests cover
both paths.

## Runtime & dependency upgrade

### Runtime

| Item | Before | After |
|------|--------|-------|
| Python | 3.7.2 (internal JPL artifactory base image) | 3.14 (`python:3.14-slim`) |
| `Dockerfile` / `.python-version` | out of sync | synchronized to 3.14 |
| pip index | internal artifactory `--extra-index-url` / `--trusted-host` | public PyPI |

### Dependencies (`image/requirements.txt`)

| Package | Before | After | Notes |
|---------|--------|-------|-------|
| tornado | 5.1.1 | 6.5.7 | web framework |
| PyJWT | 1.7.0 | 2.13.0 | **major** — decode/encode API changed (see code changes) |
| redis | 2.10.6 | 8.1.0 | **infra client** — only basic string/hash commands used (RESP2); `hmset` → `hset(mapping=)` |
| requests | 2.20.1 | 2.34.2 | security/patch updates |
| python-dateutil | 2.6.1 (duplicated) | 2.9.0.post0 | de-duplicated |
| cryptography | 2.4.2 | 50.0.0 | security-critical (RS256 backend) |
| json-logging | 1.2.0 | 1.5.1 | |
| boto3 | 1.15.8 | 1.43.65 | |
| psutil | 5.9.4 | 7.2.2 | |
| futures | 3.0.5 | **removed** | Python 2 backport; harmful on py3 |
| cffi | 1.11.2 | **removed** | transitive dep of cryptography |
| six | 1.11.0 | **removed** | transitive dep of python-dateutil |

### Code changes required by major upgrades

- **PyJWT 2.x**: `jwt.decode(..., algorithm=, verify=)` → `jwt.decode(..., algorithms=["RS256"], options={"verify_signature": ...})`; `jwt.encode()` now returns `str`, so the previous `.decode('utf-8')` calls are guarded with an `isinstance(..., bytes)` check. Affects `ingenium_library.decode_ingenium_token` / `decode_venue_token` / `refresh_ingenium_token` / `refresh_venue_tokens` and `execution_server` token minting. These are now covered by `tests/unit/ingenium_embedded/test_token_auth.py`.
- **redis-py**: the removed `hmset` command was migrated to `hset(name, mapping=...)` in the execution/step cache helpers.

### Accepted decisions

- **redis-py 8.x** (major jump from 2.10): accepted because the service uses only
  basic `get/set/hget/hset(mapping=)/hmget` over the default RESP2 protocol —
  universally compatible with all supported Redis server versions. Documented in
  `image/requirements.txt`.

### Verification

1. Unit tests: `pytest` (558 passing, ~85% coverage).
2. Docker build: `docker build -t ingenium-exec-server .`.
3. Smoke test: import all modules inside the built image (see command below).

```bash
docker build -t ingenium-exec-server .
docker run --rm ingenium-exec-server \
  python -c "import execution_server; from ingenium_embedded import ingenium_library; print('import OK')"
```