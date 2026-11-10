# Configuration

## Loading order

1. `image/config.ini` is read at process startup (`ConfigParser` in the
   `if __name__ == '__main__':` block of `image/execution_server.py`) and
   provides defaults for `HTTP_PORT`, `LOG_LEVEL`, `DEV`, `REDIS_HOST`,
   `REDIS_PORT`.
2. Environment variables **override** the `config.ini` values, using the
   `os.environ.get('X', config.get(section, 'X'))` pattern — i.e. env wins
   when set.
3. Everything else (JWT keys, service base URLs, S3/file-server settings,
   worker-pool size, verification channel tuning) has **no `config.ini`
   entry** — it is env-var-only, with either a hardcoded Python default or
   an empty-string default.
4. `image/ingenium_embedded/ingenium_config.py` reads its own subset of env
   vars (`MEDIA_BUCKET`, `FILE_SERVER_API_HOST`, the `VERIFY_*` channel
   variables) **at import time**, inside a worker subprocess — so changing
   these requires restarting workers, not just the main process.

## `image/config.ini`

```ini
[logging]
LOG_LEVEL = DEBUG

[server]
HTTP_PORT = 9999
DEV = false

[redis]
REDIS_HOST = 127.0.0.1
REDIS_PORT = 6379
```

## Environment variables

### Server / HTTP

| Variable | Default | Read by | Notes |
|---|---|---|---|
| `HTTP_PORT` | `9999` (`config.ini`) | `execution_server.py` `__main__` | Port Tornado listens on. |
| `LOG_LEVEL` | `DEBUG` (`config.ini`) | `execution_server.py` `__main__` | Sets the `Global` logger level at boot; can also be changed live via `POST /api/v4/logging` (`admin` scope). |
| `DEV` | `false` (`config.ini`) | `execution_server.py` `__main__` | When `"true"` (case-insensitive), starts `tornado.autoreload` and watches every `.py` file under the CWD. |
| `NUMBER_OF_KERNELS_MIN` | `5` (Python default in `ExecutionServer.__init__`) | `execution_server.py` | Size of the `WorkerPool` — i.e. how many executions can be actively running steps concurrently. Invalid/non-integer values fall back to `5` with a logged message. |

### Redis

| Variable | Default | Read by | Notes |
|---|---|---|---|
| `REDIS_HOST` | `127.0.0.1` (`config.ini`, used by `StateManager` in the main process) | `execution_server.py` (`ExecutionServer.__init__`) | |
| `REDIS_HOST` | `'exec_redis'` (hardcoded Python default; **different** from the main process's default) | `ingenium_library.py` module import (worker subprocess) | Both point at the same logical hash schema (`execution_id:{id}`); in any real deployment this variable must be set consistently so both processes reach the same Redis instance. |
| `REDIS_PORT` | `6379` | both of the above | Falls back to `6379` if the value isn't a valid integer, with a logged warning. |

### JWT / authentication

| Variable | Default | Read by | Notes |
|---|---|---|---|
| `PUBLIC_PEM` | `''` | `execution_server.py` (`exec_api`), `ingenium_library.decode_ingenium_token` | RSA **public** key, PEM text (not a file path), used to verify inbound Ingenium-issued JWTs (RS256). Empty by default — see [Security](Security.md) for the implication. |
| `PRIVATE_PEM` | `None` (`os.environ.get` with no default) | `ingenium_library.refresh_ingenium_token` | RSA **private** key used to re-sign a refreshed Ingenium token. Distinct from `EXEC_VENUE_PRIVATE_PEM`. |
| `EXEC_VENUE_PRIVATE_PEM` | `''` | `execution_server.py` (`RunHandler.post`, minting the per-run venue token), `ingenium_library.refresh_venue_tokens` | RSA private key used to mint/refresh the short-lived venue-service JWT. |
| `EXEC_VENUE_PUBLIC_PEM` | `''` | `ingenium_library.decode_venue_token` | RSA public key used to verify the venue-service JWT before refreshing it. |

All PEM env vars hold the **PEM-encoded key text itself**, not a filesystem
path. `.gitignore` excludes `*.pem` files from the repository, implying keys
are expected to be supplied at deploy time (e.g. via secret manager / CI
variable), not committed.

### External services

| Variable | Default | Read by | Notes |
|---|---|---|---|
| `CORE_SERVER` | `http://core_server:8080` | `ingenium_library.py` (every Core API function) | Base URL; requests append `/api/v5/executions/...`. |
| `EXECUTION_SERVER` | `http://exec_server:9999` | `ingenium_library.switch_execution` | Base URL used to call *this same service's* `/switch` endpoint from a worker subprocess — i.e. cross-worker/cross-instance execution handoff. |
| `VENUE_CONFIG_SERVER` | `http://venue_config:5151` | `ingenium_library.get_venue_configurations_url` | Base URL for the Venue Configuration Service. |

### Storage / files

| Variable | Default | Read by | Notes |
|---|---|---|---|
| `MEDIA_BUCKET` | `''` | `ingenium_config.py` (`ic.media_bucket`) | S3 bucket used by `upload_file_to_fileserver` for custom-script log tarball members. |
| `FILE_SERVER_API_HOST` | `''` | `ingenium_config.py` (`ic.file_server_api_host`) | File-server API host referenced by file-upload/download logic. |

### Command-dispatch verification tuning

Each of these controls which telemetry proves a command was dispatched (see
[Data Flows § Command dispatch](Data-flows.md#7-command-dispatch--verification-cmd-fswhw-path)).
All are read once, at `ingenium_config.py` import time, via
`get_list_from_env_var(name, ':', default)` for the list-valued ones.

| Variable | Default when unset | Default when set to `""` | Notes |
|---|---|---|---|
| `VERIFY_FSW_CHANNELS` | `['CMD-0027']` | `[]` | Colon-delimited channel-id list. |
| `VERIFY_FSW_EVR` | `'CMD_SVC_EVR_VC1_CMD_DISPATCHED'` | `''` | |
| `VERIFY_HW_CHANNELS` | `['CMD-0024']` | `[]` | Colon-delimited. |
| `VERIFY_HW_EVR` | `'CMD_SVC_EVR_VC0_COMMAND_DISPATCH'` | `''` | |
| `VERIFY_FILE_CHANNELS` | `[]` | `[]` | Colon-delimited. |
| `VERIFY_FILE_EVR` | `'FV_SVC_EVR_WRITE_NVFS_FILE_SUCCESS'` | `''` | |
| `VERIFY_EVR_MSG` | `False` | n/a | Parsed as `value.lower() == 'true'` when the var is set at all; otherwise `False`. |

The distinct unset-vs-empty-string behavior is explicit in the source
(`if os.getenv('X') is None: <mission default> else: get_list_from_env_var(...)`)
— setting the variable to an empty string is how you *disable* a default
channel list rather than merely leaving it unset.

### Misc

| Variable | Default | Read by | Notes |
|---|---|---|---|
| `EXECUTION_SWITCH_WAIT_SEC` | `'10'` | `ingenium_library.py` module import | Seconds a `wait_execution_switch` caller blocks (polling Redis every 1s) waiting for an execution-switch flag to clear. Falls back to `10` on parse failure. |
| `USERNAME` / `PASSWORD` | *(none)* | `ingenium_step_sdk.set_login_info(environment_variable=True)` | Only used by the standalone, unused-by-the-server `ingenium_step_sdk.py` helper — see [Core Components](Core-components.md). |

## Configuration NOT present in this repository

The repository does not document or implement:
- TLS/HTTPS termination for the Tornado server itself (`execution.yaml`
  declares `schemes: [http]`).
- A `.env` file convention or a secrets manager integration — all secrets
  are plain environment variables.
- Any config-file mechanism for the JWT keys, service URLs, or verification
  channel tuning — these are environment-variable-only.
