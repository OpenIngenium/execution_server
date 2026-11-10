"""Unit tests for JWT token decode/refresh in ``ingenium_library``.

These became unit-testable after the PyJWT 1.x -> 2.x upgrade (the code now uses
the ``algorithms=[...]`` / ``options={...}`` decode API and treats ``encode``
output as ``str``). RSA keys are generated in-process; Redis is mocked by the
shared autouse fixture.
"""

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from ingenium_embedded import ingenium_library as ing_lib
from ingenium_embedded import ingenium_config as ic
from ingenium_embedded.ingenium_library import (
    decode_ingenium_token,
    decode_venue_token,
    refresh_ingenium_token,
    refresh_venue_tokens,
    StepExecutionError,
)


@pytest.fixture(scope="module")
def rsa_keys():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return private_pem, public_pem


def _token(private_pem, **claims):
    payload = {"username": "pchung", "scopes": ["basic"]}
    payload.update(claims)
    return jwt.encode(payload, private_pem, algorithm="RS256")


class TestDecodeIngeniumToken:
    def test_verified_decode(self, rsa_keys, monkeypatch):
        private_pem, public_pem = rsa_keys
        monkeypatch.setenv("PUBLIC_PEM", public_pem)
        ic.ing_token = _token(private_pem)
        decoded = decode_ingenium_token(verify=True)
        assert decoded["username"] == "pchung"

    def test_unverified_decode_ignores_key(self, rsa_keys, monkeypatch):
        private_pem, _ = rsa_keys
        monkeypatch.delenv("PUBLIC_PEM", raising=False)
        ic.ing_token = _token(private_pem)
        decoded = decode_ingenium_token(verify=False)
        assert decoded["username"] == "pchung"

    def test_invalid_token_raises(self, monkeypatch):
        monkeypatch.delenv("PUBLIC_PEM", raising=False)
        ic.ing_token = "not-a-jwt"
        with pytest.raises(Exception):
            decode_ingenium_token(verify=False)


class TestDecodeVenueToken:
    def test_verified_decode(self, rsa_keys, monkeypatch):
        private_pem, public_pem = rsa_keys
        monkeypatch.setenv("EXEC_VENUE_PUBLIC_PEM", public_pem)
        ic.venue_token = _token(private_pem)
        decoded = decode_venue_token(verify=True)
        assert decoded["username"] == "pchung"


class TestRefreshIngeniumToken:
    def test_refresh_produces_str_token(self, rsa_keys, monkeypatch):
        private_pem, public_pem = rsa_keys
        monkeypatch.setenv("PRIVATE_PEM", private_pem)
        monkeypatch.setenv("PUBLIC_PEM", public_pem)
        ic.execution_id = "1"
        ic.ing_token = _token(private_pem)

        refresh_ingenium_token()

        assert isinstance(ic.ing_token, str)
        # The refreshed token is valid and carries the original claims + exp/iat.
        decoded = jwt.decode(ic.ing_token, public_pem, algorithms=["RS256"])
        assert decoded["username"] == "pchung"
        assert "exp" in decoded and "iat" in decoded
        # Redis cache write happened via the mocked client.
        ing_lib.redis_client.hset.assert_called()

    def test_undecodable_token_raises(self, monkeypatch):
        monkeypatch.setenv("PRIVATE_PEM", "x")
        ic.ing_token = "garbage"
        with pytest.raises(StepExecutionError):
            refresh_ingenium_token()


class TestRefreshVenueTokens:
    def test_refresh_produces_str_token(self, rsa_keys, monkeypatch):
        private_pem, public_pem = rsa_keys
        monkeypatch.setenv("EXEC_VENUE_PRIVATE_PEM", private_pem)
        monkeypatch.setenv("EXEC_VENUE_PUBLIC_PEM", public_pem)
        ic.execution_id = "1"
        ic.venue_token = _token(private_pem)

        refresh_venue_tokens()

        assert isinstance(ic.venue_token, str)
        decoded = jwt.decode(ic.venue_token, public_pem, algorithms=["RS256"])
        assert decoded["username"] == "pchung"

    def test_undecodable_token_raises(self, monkeypatch):
        monkeypatch.setenv("EXEC_VENUE_PRIVATE_PEM", "x")
        ic.venue_token = "garbage"
        with pytest.raises(StepExecutionError):
            refresh_venue_tokens()
