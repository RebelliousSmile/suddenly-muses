"""H1 — `/narrate` stub end-to-end + H4 — preuve du mur par test HTTP."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from muses.api.server import create_app
from muses.narrate import CannedNarrator


def _valid_request(n: int = 3) -> dict:
    return {
        "n": n,
        "packet": {
            "schema_version": 1,
            "cadre": {"lieu": "une taverne enfumée", "ambiance": None, "presents": []},
            "locuteur": {"nom": "Le Garde", "voix": "bourru"},
            "action_joueur": "Le joueur demande ce qu'il y a dans la cave.",
            "hearing": "il entend une accusation",
            "move": "se lève et barre le passage",
            "revealable": ["la cave sert d'entrepôt"],
            "withhold": ["le passage secret vers les egouts"],
            "form": {"registre": "familier", "budget_revelation": 1, "ratio": "equilibre"},
        },
    }


@pytest.fixture()
def client() -> TestClient:
    # Injection explicite du CannedNarrator : le défaut de create_app est
    # LLMNarrator (H2), qui exigerait un provider/clé.
    return TestClient(create_app(tables=[], narrator=CannedNarrator()))


def test_narrate_returns_n_string_candidates(client: TestClient) -> None:
    resp = client.post("/narrate", json=_valid_request(n=3))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["candidates"]) == 3          # exactement n
    assert all(isinstance(c, str) for c in body["candidates"])  # strings, pas {text}
    assert body["schema_version"] == 1
    assert resp.headers.get("X-Muses-Credits-Spent") == "3"


def test_narrate_includes_one_leaky_candidate(client: TestClient) -> None:
    resp = client.post("/narrate", json=_valid_request(n=3))
    texts = resp.json()["candidates"]
    assert any("passage secret vers les egouts" in t for t in texts)


def test_narrate_unknown_field_is_the_wall(client: TestClient) -> None:
    bad = _valid_request()
    bad["packet"]["secret_canon"] = "fuite de canon"
    resp = client.post("/narrate", json=bad)
    assert resp.status_code == 400
    assert resp.json()["error"] == "bad_request"


def test_narrate_wrong_version_is_409(client: TestClient) -> None:
    bad = _valid_request()
    bad["packet"]["schema_version"] = 2
    resp = client.post("/narrate", json=bad)
    assert resp.status_code == 409
    assert resp.json()["error"] == "schema_incompatible"


def test_narrate_n_out_of_bounds_is_400(client: TestClient) -> None:
    resp = client.post("/narrate", json=_valid_request(n=9))
    assert resp.status_code == 400
    assert resp.json()["error"] == "bad_request"


def test_narrate_malformed_json_is_400(client: TestClient) -> None:
    resp = client.post(
        "/narrate",
        content=b"{not json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400


def test_health_still_green(client: TestClient) -> None:
    assert client.get("/v1/health").json()["status"] == "ok"
