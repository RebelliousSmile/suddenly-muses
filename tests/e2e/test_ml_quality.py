"""Tests e2e/ml — qualité du runner local Muse et des axes canoniques.

Ces vérifications ciblent l'instance locale complète lancée par
`scripts/run_muse_full_local.sh` : on veut vérifier la traçabilité des
suggestions, le relâchement hiérarchique des axes, le cycle de feedback et
les analyseurs de cohérence / liens fédérés.
"""

from __future__ import annotations

import os
from typing import Any, Generator

import httpx
import pytest

BASE_URL = os.environ.get("MUSES_BASE_URL", "http://127.0.0.1:8001")
SIGNATURE_HEADERS = {"Signature": 'keyId="x",signature="abc"'}

CANONICAL_CONTEXT = {
    "univers": ["medieval_fantastique"],
    "situation": ["combat"],
    "rapport_initial": ["hostile"],
    "voix": ["solennel"],
    "emotion_dominante": ["colere"],
}

RELAXED_CONTEXT = {
    "univers": ["cyberpunk"],
    "situation": ["exploration"],
    "rapport_initial": ["amical"],
    "voix": ["lyrique"],
    "emotion_dominante": ["joie"],
}


@pytest.fixture(scope="session")
def api_client() -> Generator[httpx.Client, None, None]:
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
        yield client


def _suggest(
    client: httpx.Client,
    *,
    context_tags: dict[str, list[str]],
    user_id: str,
    mode: str = "confort",
    context_text: str = "Le chevalier brandit sa lame avec calme devant l'ennemi.",
) -> dict[str, Any]:
    resp = client.post(
        "/v1/suggest/dialogue",
        json={
            "feature": "dialogue",
            "context_text": context_text,
            "context_tags": context_tags,
            "n_candidates": 3,
            "top_n": 2,
            "mode": mode,
            "user_id": user_id,
        },
        headers=SIGNATURE_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.e2e
@pytest.mark.ml
def test_health_reports_full_local_runner(api_client: httpx.Client) -> None:
    health = api_client.get("/v1/health").json()
    assert health["status"] == "ok"
    assert health["tables_count"] >= 1
    assert health["feedback_enabled"] is True
    assert health["signature_mode"] == "stub"
    assert health["encoder_dim"] >= 16


@pytest.mark.e2e
@pytest.mark.ml
def test_canonical_dialogue_suggestions_are_traced(api_client: httpx.Client) -> None:
    payload = _suggest(
        api_client,
        context_tags=CANONICAL_CONTEXT,
        user_id="phase6-trace-user",
    )

    assert payload["selected_table_count"] >= 1
    assert payload["weighted_count"] > 0
    assert payload["relaxed_axes"] == []
    assert payload["suggestions"]
    for suggestion in payload["suggestions"]:
        assert suggestion["source_row_ids"]
        assert suggestion["source_scores"]


@pytest.mark.e2e
@pytest.mark.ml
def test_incompatible_dialogue_context_relaxes_all_axes(api_client: httpx.Client) -> None:
    payload = _suggest(
        api_client,
        context_tags=RELAXED_CONTEXT,
        user_id="phase6-relax-user",
    )

    assert payload["suggestions"]
    assert payload["selected_table_count"] >= 1
    assert payload["relaxed_axes"] == [
        "emotion_dominante",
        "voix",
        "rapport_initial",
        "situation",
        "univers",
    ]


@pytest.mark.e2e
@pytest.mark.ml
def test_feedback_signal_is_recorded_and_penalizes_challenge_rows(api_client: httpx.Client) -> None:
    user_id = "phase6-challenge-user"
    comfort = _suggest(
        api_client,
        context_tags=CANONICAL_CONTEXT,
        user_id=user_id,
        mode="confort",
    )
    row_id = comfort["suggestions"][0]["source_row_ids"][0]

    for _ in range(20):
        resp = api_client.post(
            "/v1/feedback/signal",
            json={
                "signal": "accept",
                "user_id": user_id,
                "instance_id": "local",
                "feature": "dialogue",
                "row_id": row_id,
                "contributor_user_id": "author",
                "contributor_instance_id": "public",
                "context_tags": CANONICAL_CONTEXT,
            },
            headers=SIGNATURE_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["recorded"] is True

    challenge = _suggest(
        api_client,
        context_tags=CANONICAL_CONTEXT,
        user_id=user_id,
        mode="challenge",
    )

    assert challenge["suggestions"]
    assert challenge["suggestions"][0]["source_scores"][0] < comfort["suggestions"][0]["source_scores"][0]


@pytest.mark.e2e
@pytest.mark.ml
def test_analysis_endpoints_return_quality_signals(api_client: httpx.Client) -> None:
    scene = api_client.post(
        "/v1/analyze/consistency_scene",
        json={
            "scene_fragments": [
                "Il dégaine son épée.",
                "Il caresse doucement sa main.",
            ]
        },
        headers=SIGNATURE_HEADERS,
    )
    assert scene.status_code == 200, scene.text
    scene_payload = scene.json()
    assert scene_payload["n_issues"] == 1
    assert scene_payload["issues"][0]["severity"] == "warn"

    links = api_client.post(
        "/v1/analyze/federated_links",
        json={
            "session_characters": {
                "Ariane": "une guerrière calme avec une armure gravée et une lame ancienne",
            },
            "public_characters": {
                "p1": "guerrière d'armure ancienne, calme, fidèle à la lame",
                "p2": "marchand bavard en veste de cuir",
            },
            "threshold": 0.8,
        },
        headers=SIGNATURE_HEADERS,
    )
    assert links.status_code == 200, links.text
    links_payload = links.json()
    assert len(links_payload["suggestions"]) == 1
    assert links_payload["suggestions"][0]["confidence"] == "fort"
