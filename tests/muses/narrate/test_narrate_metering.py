"""H3 — métrage `/narrate` bout-en-bout : auth + portefeuille (contrat CN)."""

from __future__ import annotations

import time

import jwt
import pytest
from fastapi.testclient import TestClient

from muses.api.server import create_app
from muses.narrate import (
    CannedNarrator,
    JwtSessionVerifier,
    WalletStore,
    make_session_dependency,
)

SECRET = "test-secret-0123456789-abcdefghij-LONG"  # >= 32 bytes (HMAC SHA256)


def _token(*, sub="u1", iss="muse.example", ttl=3600) -> str:
    return jwt.encode(
        {"sub": sub, "iss": iss, "exp": int(time.time()) + ttl}, SECRET, algorithm="HS256"
    )


def _request(n: int = 3) -> dict:
    return {
        "n": n,
        "packet": {
            "schema_version": 1,
            "cadre": {"lieu": "une taverne", "ambiance": None, "presents": []},
            "locuteur": {"nom": "Le Garde", "voix": "bourru"},
            "action_joueur": "Le joueur entre.",
            "hearing": "il entend une menace",
            "move": "barre la porte",
            "revealable": [],
            "withhold": [],
            "form": {"registre": "sec", "budget_revelation": 0, "ratio": "equilibre"},
        },
    }


def _client(tmp_path, *, default_grant: int) -> tuple[TestClient, WalletStore]:
    wallet = WalletStore(tmp_path / "w.sqlite", default_grant=default_grant)
    app = create_app(
        tables=[],
        narrator=CannedNarrator(),
        narrate_session_auth=make_session_dependency(JwtSessionVerifier(key=SECRET)),
        narrate_wallet=wallet,
    )
    return TestClient(app, raise_server_exceptions=False), wallet


def test_authenticated_call_debits_n(tmp_path) -> None:
    client, wallet = _client(tmp_path, default_grant=100)
    resp = client.post(
        "/narrate", json=_request(n=3), headers={"Authorization": f"Bearer {_token()}"}
    )
    assert resp.status_code == 200
    assert len(resp.json()["candidates"]) == 3
    assert resp.headers.get("X-Muses-Credits-Spent") == "3"
    assert wallet.balance("muse.example/u1") == 97


def test_missing_token_is_401_unauthorized(tmp_path) -> None:
    client, _ = _client(tmp_path, default_grant=100)
    resp = client.post("/narrate", json=_request())
    assert resp.status_code == 401
    assert resp.json()["error"] == "unauthorized"


def test_invalid_token_is_401(tmp_path) -> None:
    client, _ = _client(tmp_path, default_grant=100)
    bad = jwt.encode(
        {"sub": "u1", "iss": "m", "exp": int(time.time()) + 60},
        "wrong-secret-0123456789-abcdefghij-ZZ",
        algorithm="HS256",
    )
    resp = client.post("/narrate", json=_request(), headers={"Authorization": f"Bearer {bad}"})
    assert resp.status_code == 401


def test_insufficient_wallet_is_402_quota(tmp_path) -> None:
    # Contrat CN : exactement n candidats. Solde < n → refus, pas de n=1.
    client, wallet = _client(tmp_path, default_grant=2)
    resp = client.post(
        "/narrate", json=_request(n=3), headers={"Authorization": f"Bearer {_token()}"}
    )
    assert resp.status_code == 402
    assert resp.json()["error"] == "quota_exhausted"
    assert wallet.balance("muse.example/u1") == 2  # rien débité


def test_exact_wallet_serves_full_n(tmp_path) -> None:
    client, wallet = _client(tmp_path, default_grant=3)
    resp = client.post(
        "/narrate", json=_request(n=3), headers={"Authorization": f"Bearer {_token()}"}
    )
    assert resp.status_code == 200
    assert len(resp.json()["candidates"]) == 3
    assert wallet.balance("muse.example/u1") == 0
