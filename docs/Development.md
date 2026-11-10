# Development

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

`requirements-dev.txt` installs the test toolchain (`pytest`, `pytest-cov`,
`pytest-mock`) plus every runtime library the source imports at module level
(`requests`, `redis`, `pyjwt`, `boto3`, `json-logging`, `python-dateutil`,
`psutil`, `cryptography`, `tornado`) — unpinned, unlike `image/requirements.txt`.
It deliberately does **not** duplicate the production pins; the comment at
the top of the file explains this is safe because unit tests mock every
external collaborator (Redis, HTTP, S3) rather than exercising real
version-specific network behavior.

For running the *production* image dependencies exactly as deployed, install
`image/requirements.txt` instead:

```bash
pip install -r image/requirements.txt
```

## Running the server locally

```bash
cd image
python execution_server.py
```

This binds `HTTP_PORT` (default `9999`) and requires a reachable Redis at
`REDIS_HOST`/`REDIS_PORT` (default `127.0.0.1:6379` for the main process —
see [Configuration](Configuration.md) for the worker-subprocess default
mismatch). Without Redis, requests to Redis-backed routes will error; without
`PUBLIC_PEM` set, every authenticated route will fail JWT verification (see
[Security](Security.md)).

Health check (no auth, no Redis dependency):

```bash
curl http://localhost:9999/api/v4/health
```

Set `DEV=true` to enable Tornado's autoreload (watches every `.py` file
under the process's working directory and restarts on change) — useful for
iterating on handler code without restarting manually.

## Running in Docker

```bash
docker build -t ingenium-exec-server .
docker run --rm -p 9999:9999 ingenium-exec-server
```

The `Dockerfile` is minimal: `FROM python:3.14-slim`, `COPY ./image /app`,
`pip install -r requirements.txt`, `EXPOSE 9999`, `CMD ["python", "execution_server.py"]`.
There is no multi-stage build, no non-root user, and no health-check
directive defined in the `Dockerfile` itself.

To pass configuration/secrets into the container, use `-e`/`--env-file` with
the variables documented in [Configuration](Configuration.md), e.g.:

```bash
docker run --rm -p 9999:9999 \
  -e REDIS_HOST=host.docker.internal \
  -e PUBLIC_PEM="$(cat public.pem)" \
  ingenium-exec-server
```

## Running tests

```bash
pytest                      # full suite with coverage (uses pyproject.toml defaults)
pytest tests/unit --no-cov  # faster iteration, coverage reporting disabled
pytest tests/unit/ingenium_embedded/test_cmd_step.py -q   # a single module
```

See [Testing](Testing.md) for how the suite is structured and how
Redis/HTTP/S3 are mocked.

## Linting, formatting, type checking

**None of these are configured in this repository.** There is no
`ruff`/`flake8`/`pylint` config, no `black`/`isort` config, no `mypy`/`pyright`
config, and no `pre-commit` hook file. `pyproject.toml` contains only
`[tool.pytest.ini_options]` and `[tool.coverage.*]` sections. If you add such
tooling, update this page and [CI/CD](Cicd.md) together so the two stay
consistent.

## Debugging

Practical, code-grounded starting points (not a documented "debugging guide"
— the repository does not provide one):

- **Structured logs**: every step-level log statement passes `extra={"event":
  ..., "data": ...}` to the standard `logging` module; the `Global` logger
  (main process) uses a plain `StreamHandler`, while `ingenium_embedded`'s
  logger (worker subprocess) is formatted as JSON by `CustomJSONLog`
  (`image/ingenium_embedded/json_log_config.py`). Filter/grep on the `event`
  field (see [Error Handling](Error-handling.md) for the full `EventName`
  vocabulary) to trace a specific step's lifecycle.
- **Runtime log-level changes**: `POST /api/v4/logging` with `admin` scope
  changes the `Global` logger's level without a restart — useful for turning
  on `DEBUG` against a live instance temporarily.
- **Worker state is process-local**: because `ingenium_config` state lives
  inside a specific `WorkerProcess` subprocess, a bug that only reproduces
  "on the second step of an execution" is almost certainly related to state
  carried in `ic.*` from the first step — inspect what the first step wrote
  into `ic.variables`/`ic.channel_variables`/`ic.time_references`/etc.
- **`run_dummy` fake-venue mode**: setting
  `manual_input_variables['step_function_name'].actual_value = 'run_dummy'`
  (see [API Reference](Api-reference.md#the-run_dummy-fake-venue-convention))
  lets you exercise the Execution Server's own control flow (worker pool,
  auth, Core reporting) without a real Venue Service, for a subset of step
  types.
- **Broken worker recovery**: if a worker subprocess dies unexpectedly,
  `WorkerProcess.reset()` logs at `INFO`/`WARNING` while it
  `SIGTERM`/`SIGKILL`s and rebuilds the pool slot; look for
  `"Failed to terminate worker process"` / `"Failed to kill worker process"`
  log lines if a worker seems stuck.
