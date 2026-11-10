"""Unit tests for ``ingenium_embedded.ingenium_step_sdk``.

All HTTP interaction is mocked; the SDK's job is to build the right URLs and
update auth state on ``ingenium_config``.
"""

import getpass

from ingenium_embedded import ingenium_step_sdk as sdk
from ingenium_embedded import ingenium_config as ic

from mocks.mock_http_client import make_response


class TestSetLoginInfo:
    def test_from_environment(self, monkeypatch):
        monkeypatch.setenv("USERNAME", "alice")
        monkeypatch.setenv("PASSWORD", "secret")
        sdk.set_login_info(environment_variable=True)
        assert sdk.valid_user == "alice"
        assert sdk.valid_password == "secret"

    def test_from_prompt(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda prompt="": "bob")
        monkeypatch.setattr(getpass, "getpass", lambda: "pw")
        sdk.set_login_info(environment_variable=False)
        assert sdk.valid_user == "bob"
        assert sdk.valid_password == "pw"


class TestLoginRefreshLogout:
    def test_login_sets_token_and_header(self, monkeypatch):
        ic.ingenium_address = "http://ingenium"
        sdk.valid_user = "u"
        sdk.valid_password = "p"
        response = make_response(200, text='{"access_token": "tok123"}')
        captured = {}

        def fake_get(url, auth=None, verify=None):
            captured["url"] = url
            return response

        monkeypatch.setattr(sdk.requests, "get", fake_get)
        sdk.login()
        assert ic.ing_token == "tok123"
        assert ic.header["Authorization"] == "Bearer tok123"
        assert captured["url"].endswith(sdk.auth_endpoint_login)

    def test_refresh_updates_token(self, monkeypatch):
        ic.ingenium_address = "http://ingenium"
        response = make_response(200, text='{"access_token": "newtok"}')
        monkeypatch.setattr(sdk.requests, "post", lambda *a, **k: response)
        sdk.refresh()
        assert ic.ing_token == "newtok"
        assert ic.header["Authorization"] == "Bearer newtok"

    def test_logout_clears_token(self, monkeypatch):
        ic.ingenium_address = "http://ingenium"
        monkeypatch.setattr(sdk.requests, "post", lambda *a, **k: make_response(200))
        sdk.logout()
        assert ic.ing_token is None
        assert ic.header["Authorization"] is None


class TestGetVenues:
    def test_get_venues_returns_parsed_json(self, monkeypatch):
        ic.ingenium_address = "http://ingenium"
        response = make_response(200, text='[{"id": 1}]')
        captured = {}

        def fake_get(url, headers=None, verify=None):
            captured["url"] = url
            return response

        monkeypatch.setattr(sdk.requests, "get", fake_get)
        venues = sdk.get_venues()
        assert venues == [{"id": 1}]
        assert captured["url"].endswith(sdk.core_endpoint_venue)
