"""Unit tests for ``get_venue_config`` / ``update_venue_config`` HTTP wrappers.

``requests`` is mocked; these verify response parsing and error handling.
"""

import pytest

from ingenium_embedded import ingenium_library as ing_lib
from ingenium_embedded import ingenium_config as ic
from ingenium_embedded.ingenium_library import (
    get_venue_config,
    update_venue_config,
    StepExecutionError,
)

from mocks.mock_http_client import make_response


RAW_CONFIG = [
    {"elem_name": "A", "type": "EM", "status": "INSTALLED", "serial_number": "1", "elem_id": "id1"},
]


class TestGetVenueConfig:
    def setup_method(self):
        ic.venue_service_address = "http://vs"
        ic.venue_id = "10"
        ic.ing_token = "tok"

    def test_success(self, monkeypatch):
        import json as _json

        monkeypatch.setattr(ing_lib.requests, "get", lambda *a, **k: make_response(200, text=_json.dumps(RAW_CONFIG)))
        result = get_venue_config()
        assert result[0]["config_elem_name"] == "A"
        assert result[0]["elem_id"] == "id1"

    def test_non_200_raises(self, monkeypatch):
        monkeypatch.setattr(ing_lib.requests, "get", lambda *a, **k: make_response(500, text="err"))
        with pytest.raises(StepExecutionError):
            get_venue_config()

    def test_exception_raises(self, monkeypatch):
        monkeypatch.setattr(ing_lib.requests, "get", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("down")))
        with pytest.raises(StepExecutionError):
            get_venue_config()

    def test_non_list_config_raises(self, monkeypatch):
        monkeypatch.setattr(ing_lib.requests, "get", lambda *a, **k: make_response(200, text='{"not": "list"}'))
        with pytest.raises(Exception):
            get_venue_config()


class TestUpdateVenueConfig:
    def setup_method(self):
        ic.venue_service_address = "http://vs"
        ic.venue_id = "10"
        ic.venue_name = "v"
        ic.ing_token = "tok"

    def _element(self, name="A"):
        return {
            "config_elem_name": name, "type": "EM", "status": "INSTALLED",
            "serial": "1", "notes": "n",
        }

    def test_success(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "get_venue_config", lambda: [{"config_elem_name": "A", "elem_id": "id1"}])
        monkeypatch.setattr(ing_lib.requests, "patch", lambda *a, **k: make_response(200, text='{"elem_name": "A", "status": "INSTALLED"}'))
        result = update_venue_config(self._element("A"))
        assert result["elem_name"] == "A"

    def test_element_not_found_raises(self, monkeypatch):
        monkeypatch.setattr(ing_lib, "get_venue_config", lambda: [{"config_elem_name": "OTHER", "elem_id": "id9"}])
        with pytest.raises(StepExecutionError):
            update_venue_config(self._element("A"))
