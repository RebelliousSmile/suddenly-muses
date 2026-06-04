"""H1 — `/narrate` stub end-to-end + H4 — preuve du mur par test HTTP."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from muses.api.server import create_app


def _valid_request(n: int = 3) -> dict:
    return {
        "schema_version": 1,
        "n": n,
        "packet": {
            "cadre": "Une taverne enfumée au crépuscule.",
            "locuteur": {"nom": "Le Garde", "voix": "bourru"},
            "action_joueur": "Le joueur demande ce qu'il y a dans la cave.",
            "withhold": ["le passage secret vers les egouts"],
            "form": {"registre": "familier", "budget": 60},
        },
    }


@pytest.fixture()
def client() -> TestClient:
    # tables=[] : /narrate n'utilise pas l'orchestrateur ni les tables.
    return TestClient(create_app(tables=[]))


def test_narrate_returns_n_candidates(client: TestClient) -> None:
    resp = client.post("/narrate", json=_valid_request(n=3))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["candidates"]) == 3
    assert body["credits_spent"] == 3


def test_narrate_includes_one_leaky_candidate(client: TestClient) -> None:
    # Un candidat fuyard mentionne le sujet `withhold` — le verifier CN
    # doit pouvoir l'écarter. Le Hub ne filtre rien (invariant #3).
    resp = client.post("/narrate", json=_valid_request(n=3))
    texts = [c["text"] for c in resp.json()["candidates"]]
    assert any("passage secret vers les egouts" in t for t in texts)


def test_narrate_unknown_field_is_the_wall(client: TestClient) -> None:
    # H4 — preuve exécutable : « le schéma EST le mur ».
    bad = _valid_request()
    bad["packet"]["secret_canon"] = "fuite de canon"
    resp = client.post("/narrate", json=bad)
    assert resp.status_code == 422


def test_narrate_wrong_version_rejected(client: TestClient) -> None:
    bad = _valid_request()
    bad["schema_version"] = 2
    assert client.post("/narrate", json=bad).status_code == 422


def test_narrate_n_out_of_bounds_rejected(client: TestClient) -> None:
    assert client.post("/narrate", json=_valid_request(n=9)).status_code == 422


def test_narrate_malformed_json_rejected(client: TestClient) -> None:
    resp = client.post(
        "/narrate",
        content=b"{not json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 422


def test_health_still_green(client: TestClient) -> None:
    # /narrate greffé sans casser l'existant.
    assert client.get("/v1/health").json()["status"] == "ok"
