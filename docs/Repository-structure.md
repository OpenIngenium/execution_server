# Repository Structure

```text
.
├── image/                        # Everything COPY'd into the Docker image (see Dockerfile)
│   ├── execution_server.py       # Tornado app: HTTP handlers, JWT auth, worker pool, AUTO-run loop
│   ├── state_manager.py          # StateManager: Redis-backed config_value/variable_value reads
│   ├── config.ini                # Default HTTP/logging/Redis settings (overridable by env vars)
│   ├── requirements.txt          # Production dependency pins
│   └── ingenium_embedded/        # The "embedded code" package — everything a step needs
│       ├── ingenium_config.py    # Shared MUTABLE module-level state (imported as `ic` everywhere)
│       ├── ingenium_library.py   # Core API client, venue query/command functions, ing_execution decorator
│       ├── verification_lib.py   # Verify/CommandBase class hierarchy for value & command verification
│       ├── ingenium_step_sdk.py  # Standalone login/venue-listing helpers (not used by the server runtime)
│       ├── logging_util.py       # Module logger bootstrap (JSON formatter via json_log_config)
│       ├── json_log_config.py    # CustomJSONLog formatter used by logging_util
│       └── *_step.py             # One module per step type; each exposes run(step)
├── tests/
│   └── unit/                     # Pytest suite; mirrors image/ingenium_embedded 1:1
│       ├── conftest.py           # Autouse fixtures: reset ingenium_config, mock Redis
│       ├── mocks/                # FakeRedis, requests-response builder, step-envelope factory
│       ├── test_execution_server.py
│       └── ingenium_embedded/    # test_<module>.py per source module
├── execution.yaml                # Swagger 2.0 definition of the REST API (source of truth for schemas)
├── Dockerfile                    # python:3.14-slim, COPY image/, pip install, CMD execution_server.py
├── .github/workflows/ci.yml      # GitHub Actions: pytest, then `docker build`
├── pyproject.toml                # pytest/coverage configuration (testpaths, pythonpath, addopts)
├── requirements-dev.txt          # Test-only dependencies (pytest*, plus runtime libs needed to import)
└── README.md                     # Public-facing overview, quick start, endpoint table
```

## How the pieces relate

- **`image/` is the deployable unit.** The `Dockerfile` copies only this
  directory into the image and runs `python execution_server.py` from inside
  it — nothing outside `image/` ships in the container.
- **`image/ingenium_embedded/` is imported by two different runtimes:**
  1. By `execution_server.py` in the main Tornado process, to dynamically
     dispatch a step's `code.name` to the right module (`run_step()` in
     `image/execution_server.py`).
  2. By that same module *inside* a `WorkerProcess` subprocess, where the
     step's `run()` function actually executes and where `ingenium_config`'s
     mutable state lives for the lifetime of that worker.
- **`tests/unit/` intentionally mirrors `image/ingenium_embedded/`** file for
  file (e.g. `cmd_step.py` ↔ `test_cmd_step.py`). `pyproject.toml` sets
  `pythonpath = ["image"]` so tests import `ingenium_embedded` exactly as the
  production code does, without a package install step.
- **`execution.yaml` is authoritative for the wire format.** Handler code in
  `execution_server.py` implements what this spec describes; when the two
  disagree, prefer re-reading the handler — the spec is documentation, not
  generated from code (no codegen tooling is present in this repository).
- **`.github/workflows/ci.yml` runs the public CI.** GitHub Actions runs the
  unit test suite and a Docker build smoke test on every push/PR. See
  [CI/CD](Cicd.md).

## Notable absences

The repository does not currently contain:
- A `CONTRIBUTING.md`.
- Any linting/formatting/type-checking configuration (no `.flake8`,
  `ruff.toml`, `mypy.ini`, `pre-commit` config, etc.).
- A dedicated documentation site — this `docs/` tree is the first one.
