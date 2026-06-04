"""H4 — durcissement : mur/cécité prouvés par test + CORS opt-in."""

from __future__ import annotations

from fastapi.testclient import TestClient

from muses.api.server import create_app
from muses.narrate import CannedNarrator


def _client(**kwargs) -> TestClient:
    return TestClient(create_app(tables=[], narrator=CannedNarrator(), **kwargs))


def _packet_body() -> dict:
    return {
        "schema_version": 1,
        "n": 1,
        "packet": {
            "cadre": "Une taverne.",
            "locuteur": {"nom": "Le Garde", "voix": "bourru"},
            "action_joueur": "Le joueur entre.",
            "form": {"registre": "familier", "budget": 1},
        },
    }


def test_canon_smuggling_is_blocked() -> None:
    # Cécité : aucun champ ne peut transporter du canon — schéma fermé → 422.
    body = _packet_body()
    body["packet"]["canon"] = {"secret": "le tresor est sous la dalle"}
    assert _client().post("/narrate", json=body).status_code == 422


def test_cors_allows_configured_origin() -> None:
    client = _client(narrate_cors_origins=["https://cn.example"])
    resp = client.get("/v1/health", headers={"Origin": "https://cn.example"})
    assert resp.headers.get("access-control-allow-origin") == "https://cn.example"


def test_cors_blocks_unknown_origin() -> None:
    client = _client(narrate_cors_origins=["https://cn.example"])
    resp = client.get("/v1/health", headers={"Origin": "https://evil.example"})
    assert resp.headers.get("access-control-allow-origin") != "https://evil.example"


def test_no_cors_by_default() -> None:
    resp = _client().get("/v1/health", headers={"Origin": "https://cn.example"})
    assert "access-control-allow-origin" not in resp.headers
