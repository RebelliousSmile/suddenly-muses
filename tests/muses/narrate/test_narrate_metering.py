"""H3 — métrage `/narrate` bout-en-bout : auth + portefeuille."""

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


def _packet_body(n: int = 3) -> dict:
    return {
        "schema_version": 1,
        "n": n,
        "packet": {
            "cadre": "Une taverne.",
            "locuteur": {"nom": "Le Garde", "voix": "bourru"},
            "action_joueur": "Le joueur entre.",
            "form": {"registre": "familier", "budget": 1},
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
        "/narrate", json=_packet_body(n=3), headers={"Authorization": f"Bearer {_token()}"}
    )
    assert resp.status_code == 200
    assert resp.json()["credits_spent"] == 3
    assert wallet.balance("muse.example/u1") == 97


def test_missing_token_rejected_401(tmp_path) -> None:
    client, _ = _client(tmp_path, default_grant=100)
    assert client.post("/narrate", json=_packet_body()).status_code == 401


def test_invalid_token_rejected_401(tmp_path) -> None:
    client, _ = _client(tmp_path, default_grant=100)
    bad = jwt.encode(
        {"sub": "u1", "iss": "m", "exp": int(time.time()) + 60},
        "wrong-secret-0123456789-abcdefghij-ZZ",
        algorithm="HS256",
    )
    resp = client.post(
        "/narrate", json=_packet_body(), headers={"Authorization": f"Bearer {bad}"}
    )
    assert resp.status_code == 401


def test_empty_wallet_rejected_402(tmp_path) -> None:
    client, _ = _client(tmp_path, default_grant=0)
    resp = client.post(
        "/narrate", json=_packet_body(n=2), headers={"Authorization": f"Bearer {_token()}"}
    )
    assert resp.status_code == 402


def test_low_wallet_forces_n1(tmp_path) -> None:
    # Solde 2 < n=3 → levier portefeuille bas : 1 seul candidat, 1 débité.
    client, wallet = _client(tmp_path, default_grant=2)
    resp = client.post(
        "/narrate", json=_packet_body(n=3), headers={"Authorization": f"Bearer {_token()}"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["candidates"]) == 1
    assert data["credits_spent"] == 1
    assert wallet.balance("muse.example/u1") == 1
