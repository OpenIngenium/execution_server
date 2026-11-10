# Ingenium Execution Server

**Tornado-based REST service that executes Ingenium procedure steps against test venues.**

[![CI](https://github.com/OpenIngenium/execution_server/actions/workflows/ci.yml/badge.svg)](https://github.com/OpenIngenium/execution_server/actions/workflows/ci.yml)
![Python 3.14](https://img.shields.io/badge/python-3.14-blue)
![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue)


---

## Overview

The Execution Server is the component of the Ingenium platform that actually **runs procedure
steps**. It exposes a REST API (defined in [`execution.yaml`](execution.yaml)) that lets the rest
of the Ingenium platform (e.g., the Core service) register an execution against a test venue,
submit a step (`CMD`, `MANUAL_INPUT`, `VERIFY_EHA`, `CUSTOM_SCRIPT`, `BUS_1553`, …) to run, and
query execution state.

Internally, each execution is bound to a long-lived Python worker process from a managed pool.
Steps run inside their worker's persistent interpreter so that variables, EHA/EVR time references,
and venue tokens set by one step remain available to subsequent steps in the same execution.
Execution/config state that must survive across requests is cached in Redis.

This project is for engineers building or operating the Ingenium test-automation platform, and for
contributors implementing new step types.

## Features

- **REST API** for execution lifecycle management, step execution (sync or async), configuration
  and variable lookup, and health/logging status — see [`execution.yaml`](execution.yaml).
- **Worker-process pool** (`WorkerPool` / `ProcessPoolExecutor`) that keeps per-execution state
  alive across step calls, with a configurable minimum pool size.
- **Broad step-type support** — 20+ step modules under `image/ingenium_embedded/` covering
  commanding (`CMD`, `CMD_FILE`, `CMD_SCMF`, `CMD_SSE`), telemetry/EVR verification and waiting,
  1553 bus commands, manual/GDS/EIP input steps, custom scripts, and more.
- **RS256 JWT authentication** with per-route scope enforcement (`execute:wsts`,
  `execute:testbed`, `execute:sit`, `execute:other`, `admin`).
- **Redis-backed state** for execution/config/variable values via `StateManager`.
- **Structured JSON logging** (`json-logging`) with a runtime-adjustable log level via the
  `/logging` endpoint.
- **558 automated unit tests** (~85% line coverage) that mock every external collaborator
  (Redis, venue/Core services, S3) for fast, deterministic runs.

## Installation

### Prerequisites

- Python **3.14** (see `.python-version`), or Docker.
- Redis, reachable from the server, for execution/config state.

### Docker (recommended)

```bash
docker build -t ingenium-exec-server .
```

### From source

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r image/requirements.txt
```

## Quick Start

Build and run the server in Docker, then hit the health endpoint:

```bash
docker build -t ingenium-exec-server .
docker run --rm -p 9999:9999 ingenium-exec-server
```

```bash
curl http://localhost:9999/api/v4/health
```

```json
{
    "status": "OK",
    "message": ""
}
```

The health endpoint requires no authentication. Every other endpoint requires a Bearer JWT (see
[Configuration](#configuration)) and a reachable Redis instance.

## Usage

The API is versioned under `/api/v4` and fully described in [`execution.yaml`](execution.yaml)
(Swagger 2.0). Main endpoints:

| Method | Path | Purpose |
|--------|------|---------|
| `PUT` | `/api/v4/executions/{execution_id}` | Register an execution against a venue |
| `DELETE` | `/api/v4/executions/{execution_id}` | Unregister an execution |
| `POST` | `/api/v4/executions/{execution_id}/run` | Run a step (`run_mode=SYNC\|ASYNC`) |
| `GET` | `/api/v4/executions/{execution_id}/config_value` | Read an execution configuration value |
| `GET` | `/api/v4/executions/{execution_id}/variable_value` | Read a step/manual-input variable |
| `POST` | `/api/v4/executions/{execution_id}/copy_state` | Copy state to another execution |
| `POST` | `/api/v4/executions/{execution_id}/switch` | Switch a worker to another execution |
| `POST` | `/api/v4/executions/{execution_id}/halt` | Halt a running step |
| `GET`/`POST` | `/api/v4/logging` | Read/update the server log level (`admin` scope) |
| `GET` | `/api/v4/health` | Health check (no auth) |

All routes except `/health` require an `Authorization: Bearer <JWT>` header. The token is verified
with `PUBLIC_PEM` (RS256) and must carry one of the scopes listed above for that route.

Example: register an execution, then run a step.

```bash
TOKEN="<ingenium-issued JWT>"

curl -X PUT "http://localhost:9999/api/v4/executions/exec-123" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"venue_id": "v1", "name": "WSTS-1", "ampcs_address": "wsts1.example", "type": "WSTS"}'

curl -X POST "http://localhost:9999/api/v4/executions/exec-123/run?run_mode=SYNC&elem_id=step-1" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"step_type": "MANUAL_INPUT"}'
```

## Configuration

All settings fall back to defaults in `image/config.ini`; environment variables override them at
runtime.

| Variable | Default | Purpose |
|----------|---------|---------|
| `HTTP_PORT` | `9999` (`config.ini`) | Port the Tornado server listens on. |
| `LOG_LEVEL` | `DEBUG` (`config.ini`) | Root log level. |
| `DEV` | `false` (`config.ini`) | When `true`, enables Tornado autoreload on file change. |
| `NUMBER_OF_KERNELS_MIN` | `5` (code default) | Minimum worker-process pool size. |
| `REDIS_HOST` | `127.0.0.1` (`config.ini`) | Redis host used for the execution/step cache. |
| `REDIS_PORT` | `6379` (`config.ini`) | Redis port. |
| `PUBLIC_PEM` | _(empty)_ | RSA **public** key (PEM) used to verify inbound Ingenium JWTs (RS256). |
| `EXEC_VENUE_PRIVATE_PEM` | _(empty)_ | RSA **private** key (PEM) used to mint/refresh venue-service JWTs. |
| `EXEC_VENUE_PUBLIC_PEM` | _(empty)_ | RSA **public** key (PEM) used to verify venue-service JWTs. |
| `CORE_SERVER` | `http://core_server:8080` | Base URL of the Ingenium Core service. |
| `EXECUTION_SERVER` | `http://exec_server:9999` | Base URL used for cross-worker execution switching. |
| `VENUE_CONFIG_SERVER` | `http://venue_config:5151` | Base URL of the Venue Configuration service. |
| `MEDIA_BUCKET` | _(empty)_ | S3 bucket for uploaded custom-script/command files. |
| `FILE_SERVER_API_HOST` | _(empty)_ | File-server API host used by file upload steps. |

Authentication uses RS256 asymmetric keys (PyJWT 2.x); there is no shared-secret/HMAC mode.

Advanced EHA/EVR command-dispatch verification channels (`VERIFY_FSW_CHANNELS`,
`VERIFY_FSW_EVR`, `VERIFY_HW_CHANNELS`, `VERIFY_HW_EVR`, `VERIFY_FILE_CHANNELS`,
`VERIFY_FILE_EVR`, `VERIFY_EVR_MSG`) can be tuned per mission; see
`image/ingenium_embedded/ingenium_config.py` for defaults and syntax.

## Project Structure

```text
.
├── image/                     # Application source, packaged into the Docker image
│   ├── execution_server.py    # Tornado app, HTTP handlers, worker pool
│   ├── state_manager.py       # Redis-backed execution state
│   ├── config.ini             # Default configuration
│   ├── requirements.txt       # Production dependencies
│   └── ingenium_embedded/     # Step implementations + shared libraries
├── tests/unit/                # Pytest unit tests (mirrors image/ingenium_embedded)
├── docs/                      # DeepWiki — technical/developer documentation (see below)
├── execution.yaml             # Swagger 2.0 REST API definition
├── Dockerfile
└── .github/workflows/ci.yml   # CI: tests + Docker build
```

## Development

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
```

Run the server locally (requires a reachable Redis, or accept connection errors on
Redis-backed routes):

```bash
cd image
python execution_server.py
```

Run the test suite:

```bash
pytest                    # full suite with coverage (see pyproject.toml)
pytest tests/unit --no-cov  # faster iteration, no coverage
```

No linting, formatting, or type-checking tooling is currently configured in this repository.

## Testing & CI

- **Tests**: `pytest`, configured in `pyproject.toml` (`testpaths = ["tests/unit"]`,
  `pythonpath = ["image"]`, coverage scoped to `ingenium_embedded`). Every external
  collaborator (Redis, venue/Core services, S3) is mocked, so the suite performs no real
  network, Redis, or filesystem I/O.
- **Current results**: 558 tests passing, ~85% line coverage (`pytest` output).
- **CI** (`.github/workflows/ci.yml`), on every push/PR to `devel` or `main`:
  1. `test` — sets up Python from `.python-version`, installs `requirements-dev.txt`, runs
     `pytest`.
  2. `docker` — builds the Docker image (`docker build -t ingenium-exec-server:<sha> .`).

## Documentation

The REST API is fully specified in [`execution.yaml`](execution.yaml) (Swagger 2.0) — use it as
the source of truth for request/response schemas.

For everything else — architecture, internal data flows, configuration precedence, security
boundaries, and how to extend the system with a new step type — see the **[DeepWiki](docs/README.md)**
in [`docs/`](docs/). It is written for contributors who need to understand or modify the
implementation, and it intentionally does not repeat this README's quick-start content.

## Contributing

1. Clone the repository and create a feature branch off `devel`.
2. Install dev dependencies (`pip install -r requirements-dev.txt`) and run `pytest` before
   pushing.
3. Open a pull request against `devel` or `main`; CI (tests + Docker build) runs automatically.

No `CONTRIBUTING.md` exists in this repository yet.

## License

Licensed under the Apache License 2.0. See [`LICENSE`](LICENSE).