"""Shared factory helpers for building step payloads used across unit tests.

Steps flowing through the Execution Server follow a common envelope shape. These
factories build valid envelopes so individual tests only specify the fields they
care about (UNIT_TEST_PLAN.md Phase 6 - prefer reusable factory helpers).
"""

import copy


def make_step(step_type="WAIT_STEP", user_input=None, **overrides):
    """Build a minimal, valid step envelope.

    Parameters
    ----------
    step_type: str
        The step type discriminator (e.g. ``"WAIT_STEP"``).
    user_input: dict
        Value placed at ``step['execution_user_input']``.
    overrides: dict
        Top-level keys merged into the returned step, allowing tests to set
        ``guard``, ``variable``, ``number``, etc.
    """
    step = {
        "execution_id": 1,
        "elem_id": "uuid-step-1",
        "number": "1",
        "step_type": step_type,
        "variable": {"name": "var"},
        "execution_user_input": copy.deepcopy(user_input) if user_input else {},
        "execution": {
            "meta_data": {
                "status": "",
                "time_started": "2020-01-01T00:00:00.000Z",
            },
            "results": {},
        },
    }
    step.update(overrides)
    return step
