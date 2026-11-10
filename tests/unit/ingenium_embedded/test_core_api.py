"""Unit tests for the Core-service execution/step API wrappers in
``ingenium_library``.

These uniformly return ``(json, None)`` on success and ``(None, error_msg)`` on
failure. Token refresh, auth header and ``requests`` are mocked.
"""

import pytest

from ingenium_embedded import ingenium_library as ing_lib
from ingenium_embedded.ingenium_library import (
    update_execution,
    get_execution,
    get_element,
    get_simple_elements,
    get_execution_step,
    compute_step,
    create_new_run,
    import_procedure_section,
    call_procedure_section,
    switch_execution,
    suspend_resume_execution,
    post_execution_message,
    handle_execution_error,
)

from mocks.mock_http_client import make_response


@pytest.fixture(autouse=True)
def patch_auth(monkeypatch):
    monkeypatch.setattr(ing_lib, "refresh_ingenium_token", lambda: None)
    monkeypatch.setattr(ing_lib, "get_ing_authorization_header", lambda: {"Authorization": "Bearer x"})


class TestJsonReturningWrappers:
    """All of these return ``(json, None)`` on 200 and ``(None, msg)`` otherwise."""

    CASES = [
        ("get", get_execution, (1,)),
        ("get", get_element, (1, "e")),
        ("get", get_simple_elements, (1,)),
        ("get", get_execution_step, (1, "e")),
        ("post", compute_step, (1, "e")),
        ("post", create_new_run, (1, "e")),
        ("post", import_procedure_section, (1, "e")),
        ("post", call_procedure_section, (1, "e")),
        ("post", suspend_resume_execution, (1, 2)),
    ]

    @pytest.mark.parametrize("verb,func,args", CASES)
    def test_success(self, monkeypatch, verb, func, args):
        monkeypatch.setattr(ing_lib.requests, verb, lambda *a, **k: make_response(200, json_data={"ok": True}))
        data, err = func(*args)
        assert data == {"ok": True}
        assert err is None

    @pytest.mark.parametrize("verb,func,args", CASES)
    def test_failure(self, monkeypatch, verb, func, args):
        monkeypatch.setattr(ing_lib.requests, verb, lambda *a, **k: make_response(500, text="err"))
        data, err = func(*args)
        assert data is None
        assert err is not None


class TestUpdateExecution:
    def test_success(self, monkeypatch):
        monkeypatch.setattr(ing_lib.requests, "patch", lambda *a, **k: make_response(200, json_data={"status": "IDLE"}))
        assert update_execution(1, {"status": "IDLE"}) == {"status": "IDLE"}

    def test_failure_returns_none(self, monkeypatch):
        monkeypatch.setattr(ing_lib.requests, "patch", lambda *a, **k: make_response(500, text="err"))
        assert update_execution(1, {"status": "IDLE"}) is None


class TestSwitchExecution:
    def test_success_204(self, monkeypatch):
        monkeypatch.setattr(ing_lib.requests, "post", lambda *a, **k: make_response(204))
        data, err = switch_execution(1, 2)
        assert data is None and err is None

    def test_failure(self, monkeypatch):
        monkeypatch.setattr(ing_lib.requests, "post", lambda *a, **k: make_response(500, text="err"))
        data, err = switch_execution(1, 2)
        assert err is not None


class TestPostExecutionMessage:
    def test_204_no_warning(self, monkeypatch):
        monkeypatch.setattr(ing_lib.requests, "post", lambda *a, **k: make_response(204))
        # Should complete without raising.
        assert post_execution_message(1, "INFO", "hi") is None

    def test_non_204_logs(self, monkeypatch):
        monkeypatch.setattr(ing_lib.requests, "post", lambda *a, **k: make_response(500))
        assert post_execution_message(1, "INFO", "hi") is None


class TestHandleExecutionError:
    def test_reports_and_idles(self, monkeypatch):
        calls = {}
        monkeypatch.setattr(ing_lib, "report_step_results2", lambda *a, **k: calls.setdefault("report", a))
        monkeypatch.setattr(ing_lib, "update_execution", lambda *a, **k: calls.setdefault("update", a))
        handle_execution_error(1, "e", "boom")
        assert calls["report"][0] == 1
        assert calls["update"][1] == {"status": "IDLE"}
