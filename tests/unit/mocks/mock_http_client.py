"""Reusable factory helpers for mocking the ``requests`` HTTP client.

Unit tests must never perform real HTTP requests (UNIT_TEST_PLAN.md Phase 6).
These helpers build lightweight ``requests.Response``-like doubles so tests can
assert on how the source reacts to a given status code / payload.
"""

from unittest.mock import MagicMock


def make_response(status_code=200, json_data=None, text=""):
    """Build a mock object mimicking the subset of ``requests.Response`` used
    by the source under test.

    Parameters
    ----------
    status_code: int
        HTTP status code exposed as ``response.status_code``.
    json_data: object
        Value returned by ``response.json()``. If ``text`` is not supplied it is
        derived from this value.
    text: str
        Raw response body exposed as ``response.text``.
    """
    response = MagicMock(name="Response")
    response.status_code = status_code
    response.json.return_value = json_data
    if text:
        response.text = text
    elif json_data is not None:
        import json as _json

        response.text = _json.dumps(json_data)
    else:
        response.text = ""
    return response


def make_requests_mock(default_response=None):
    """Return a MagicMock standing in for the ``requests`` module.

    Every verb (get/post/patch/put/delete) returns ``default_response`` (a 200
    empty response by default). Tests may override ``.return_value`` or
    ``.side_effect`` on individual verbs.
    """
    if default_response is None:
        default_response = make_response(200, json_data={})

    requests_mock = MagicMock(name="requests")
    for verb in ("get", "post", "patch", "put", "delete"):
        getattr(requests_mock, verb).return_value = default_response
    return requests_mock
