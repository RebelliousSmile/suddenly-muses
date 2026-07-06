"""H3 — vérification du token de session (D18)."""

from __future__ import annotations

import time

import jwt
import pytest

from muses.narrate.session import (
    JwtSessionVerifier,
    SessionTokenError,
    StubSessionVerifier,
)

SECRET = "test-secret-0123456789-abcdefghij-LONG"  # >= 32 bytes (HMAC SHA256)


def _token(secret: str = SECRET, *, sub="u1", iss="muse.example", ttl=3600, alg="HS256") -> str:
    payload = {"sub": sub, "iss": iss, "exp": int(time.time()) + ttl}
    return jwt.encode(payload, secret, algorithm=alg)


def test_jwt_valid_token_resolves_wallet_key() -> None:
    claims = JwtSessionVerifier(key=SECRET).verify(_token())
    assert claims.wallet_key == "muse.example/u1"
    assert claims.user_id == "u1"
    assert claims.issuer == "muse.example"


def test_jwt_wrong_secret_rejected() -> None:
    with pytest.raises(SessionTokenError):
        JwtSessionVerifier(key=SECRET).verify(
            _token(secret="other-secret-0123456789-abcdefghij-XX")
        )


def test_jwt_expired_token_rejected() -> None:
    with pytest.raises(SessionTokenError):
        JwtSessionVerifier(key=SECRET).verify(_token(ttl=-10))


def test_jwt_missing_claims_rejected() -> None:
    token = jwt.encode({"exp": int(time.time()) + 60}, SECRET, algorithm="HS256")
    with pytest.raises(SessionTokenError):
        JwtSessionVerifier(key=SECRET).verify(token)


def test_jwt_issuer_allowlist_enforced() -> None:
    verifier = JwtSessionVerifier(key=SECRET, issuers=["muse.allowed"])
    with pytest.raises(SessionTokenError):
        verifier.verify(_token(iss="muse.example"))
    ok = verifier.verify(_token(iss="muse.allowed"))
    assert ok.issuer == "muse.allowed"


def test_stub_verifier_decodes_without_signature() -> None:
    # Le stub accepte un token signé avec n'importe quel secret (dev).
    claims = StubSessionVerifier().verify(
        _token(secret="whatever-but-long-enough-0123456789-AB")
    )
    assert claims.wallet_key == "muse.example/u1"
