"""H2 — `LLMNarrator` avec provider factice (zéro réseau en CI)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from muses.api.server import create_app
from muses.narrate import LLMNarrator
from pipelines.evaluation.providers import (
    CompletionRequest,
    CompletionResponse,
    ProviderError,
)


class FakeProvider:
    name = "fake"

    def __init__(self, content: str = "Un beat de narration.") -> None:
        self.content = content
        self.calls: list[CompletionRequest] = []

    def chat_completion(self, request: CompletionRequest) -> CompletionResponse:
        self.calls.append(request)
        return CompletionResponse(content=self.content, model=request.model, raw={})


class ExplodingProvider:
    name = "boom"

    def chat_completion(self, request: CompletionRequest) -> CompletionResponse:
        raise ProviderError("simulated upstream 500")


def _packet() -> dict:
    return {
        "schema_version": 1,
        "cadre": {"lieu": "une taverne", "ambiance": "enfumée", "presents": []},
        "locuteur": {"nom": "Le Garde", "voix": "bourru"},
        "action_joueur": "Le joueur demande ce qu'il y a dans la cave.",
        "hearing": "il entend une accusation",
        "move": "se lève et barre le passage",
        "revealable": ["la cave sert d'entrepot"],
        "withhold": ["qui a paye la rancon"],
        "form": {"registre": "tendu", "budget_revelation": 1, "ratio": "equilibre"},
    }


def _request(n: int = 2) -> dict:
    return {"n": n, "packet": _packet()}


def test_llm_narrator_returns_n_candidates() -> None:
    narrator = LLMNarrator(provider=FakeProvider("beat X"))
    assert narrator.narrate(_packet(), n=3) == ["beat X", "beat X", "beat X"]


def test_llm_narrator_makes_n_calls() -> None:
    fake = FakeProvider()
    LLMNarrator(provider=fake).narrate(_packet(), n=4)
    assert len(fake.calls) == 4


def test_llm_narrator_withhold_rendered_as_label() -> None:
    prompt = LLMNarrator(provider=FakeProvider()).render_packet(_packet())
    assert "qui a paye la rancon" in prompt
    assert "TAIRE" in prompt


def test_llm_narrator_move_and_hearing_rendered() -> None:
    prompt = LLMNarrator(provider=FakeProvider()).render_packet(_packet())
    assert "se lève et barre le passage" in prompt   # move
    assert "il entend une accusation" in prompt       # hearing (string)


def test_llm_narrator_prompt_contains_no_canon() -> None:
    prompt = LLMNarrator(provider=FakeProvider()).render_packet(_packet())
    assert "le tresor est sous la troisieme dalle" not in prompt
    assert "tenir compte" not in prompt.lower()


def test_llm_narrator_provider_error_propagates() -> None:
    with pytest.raises(ProviderError):
        LLMNarrator(provider=ExplodingProvider()).narrate(_packet(), n=2)


def test_narrate_endpoint_with_llm_swap() -> None:
    app = create_app(tables=[], narrator=LLMNarrator(provider=FakeProvider("beat HTTP")))
    resp = TestClient(app).post("/narrate", json=_request(n=2))
    assert resp.status_code == 200
    assert resp.json()["candidates"] == ["beat HTTP", "beat HTTP"]


def test_narrate_endpoint_provider_error_is_502() -> None:
    app = create_app(tables=[], narrator=LLMNarrator(provider=ExplodingProvider()))
    resp = TestClient(app, raise_server_exceptions=False).post("/narrate", json=_request(n=2))
    assert resp.status_code == 502
    body = resp.json()
    assert body["error"] == "provider_error"
    assert body["retriable"] is True
