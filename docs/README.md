# Ingenium Execution Server — DeepWiki

This is the **technical knowledge base** for the Execution Server repository. It
complements the top-level [`README.md`](../README.md), which answers *"should I
use this and how do I start it?"*. DeepWiki answers *"how does this actually
work, and how do I safely change it?"*.

Everything here is derived directly from the source in this repository
(`image/`, `tests/`, `execution.yaml`, `Dockerfile`, `.github/workflows/`,
`pyproject.toml`). Where the repository does not document a
design decision, that is called out explicitly instead of being guessed at.

## How to read this wiki

| # | Page | Answers |
|---|------|---------|
| 1 | [Project Overview](Overview.md) | What is this system, what does it do, what stack does it use? |
| 2 | [Repository Structure](Repository-structure.md) | What lives where, and why? |
| 3 | [Architecture](Architecture.md) | What are the major components and how do they interact? |
| 4 | [Core Components](Core-components.md) | What does each module/class do, in detail? |
| 5 | [API Reference](Api-reference.md) | What REST endpoints and Python interfaces exist? |
| 6 | [Data Flows](Data-flows.md) | How does a request actually travel through the system, end to end? |
| 7 | [Configuration](Configuration.md) | What environment variables/files control behavior, and in what order? |
| 8 | [Development](Development.md) | How do I set up, run, and debug this locally? |
| 9 | [Testing](Testing.md) | How is the test suite structured, and how do I run/extend it? |
| 10 | [CI/CD](Cicd.md) | What does GitHub Actions actually do on push/PR? |
| 11 | [Security](Security.md) | How is auth implemented? What are the trust boundaries? |
| 12 | [Error Handling](Error-handling.md) | How are errors modeled, logged, and reported to Core? |
| 13 | [Extending the System](Extending.md) | How do I add a new step type or API route? |
| 14 | [Troubleshooting](Troubleshooting.md) | What documented failure modes exist? |

## Conventions used throughout this wiki

- **Execution Server** — this repository/service (`image/execution_server.py`).
- **Core** / **Core service** — the external Ingenium Core service reached via
  `CORE_SERVER` (see [`ingenium_library.py`](../image/ingenium_embedded/ingenium_library.py)).
  Its API is *consumed*, not implemented, by this repository.
- **Venue Service** — the external, per-testbed service reached at the
  `ampcs_address` registered for an execution (`ic.venue_service_address`).
- **Venue Configuration Service** — the external service reached via
  `VENUE_CONFIG_SERVER`.
- **Step module** — one of the `*_step.py` files under
  `image/ingenium_embedded/` that implements a `run(step)` entry point.
- **`ic`** — the conventional import alias for `ingenium_config` used across
  almost every module in `image/ingenium_embedded/`.
- **`ing_lib`** — the conventional import alias for `ingenium_library`.

Every claim in this wiki is labeled implicitly by how it is written:
- Plain statements describe **observed implementation** (verified by reading
  the source at the cited path/line).
- Sentences starting with "Likely" / "This suggests" mark **strong inference**
  — a reasonable reading of the code where the *why* isn't stated anywhere.
- Sentences starting with "The repository does not document..." mark
  **unknowns** — do not treat these as gaps to fill with speculation.
