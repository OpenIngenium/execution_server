"""Global pytest fixtures for the Execution Server unit-test suite.

Design goals (UNIT_TEST_PLAN.md Phases 3 & 6):
- No real I/O: Redis and HTTP are always mocked.
- Deterministic & isolated: mutable ``ingenium_config`` state is reset between
  every test so tests can run independently, in any order.
"""

import os
import sys
import copy

import pytest

# Ensure the production source package (image/ingenium_embedded) is importable.
# pyproject.toml also sets pythonpath, but adding it here keeps the suite
# runnable via a bare `pytest tests/unit/...` invocation from any CWD.
_IMAGE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "image",
)
if _IMAGE_DIR not in sys.path:
    sys.path.insert(0, _IMAGE_DIR)

from ingenium_embedded import ingenium_config as ic  # noqa: E402
from ingenium_embedded import ingenium_library as ing_lib  # noqa: E402

# Names of mutable module-level attributes on ingenium_config that tests may
# touch. They are snapshotted before each test and restored afterwards.
_MUTABLE_CONFIG_ATTRS = [
    "username",
    "variables",
    "environment_step_variables",
    "manual_input_variables",
    "channel_variables",
    "cmd_variables",
    "mil_1553_variables",
    "ing_token",
    "venue_token",
    "run_mode",
    "last_step_status",
    "time_references",
    "execution_id",
    "venue_service_address",
    "venue_sse",
    "venue_name",
    "venue_id",
    "venue_type",
    "ingenium_address",
    "ampcs_session_information",
    "header",
]


@pytest.fixture(autouse=True)
def reset_ingenium_config():
    """Snapshot and restore mutable ``ingenium_config`` state around each test."""
    snapshot = {
        attr: copy.deepcopy(getattr(ic, attr)) for attr in _MUTABLE_CONFIG_ATTRS
    }
    # Default runtime mode for unit tests: SYNC keeps the ing_execution
    # decorator from attempting to report intermediate results over HTTP.
    ic.run_mode = "SYNC"
    yield
    for attr, value in snapshot.items():
        setattr(ic, attr, value)


@pytest.fixture(autouse=True)
def mock_redis_client(monkeypatch):
    """Replace the module-level Redis client with a MagicMock.

    The ``ing_execution`` decorator caches state in Redis on every step; without
    this fixture those calls would attempt a real network connection.
    """
    from unittest.mock import MagicMock

    fake = MagicMock(name="redis_client")
    monkeypatch.setattr(ing_lib, "redis_client", fake)
    return fake


@pytest.fixture
def make_step():
    """Expose the step factory as a fixture for convenience."""
    from mocks.test_helpers import make_step as _make_step

    return _make_step
