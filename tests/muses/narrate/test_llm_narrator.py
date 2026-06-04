"""H2 — `LLMNarrator` avec provider factice (zéro réseau en CI).

Prouve : best-of-N, cécité au canon dans le prompt construit, propagation
d'erreur provider, et swap d'injection bout-en-bout sans toucher au router.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from muses.api.server import create_app
from muses.narrate import LLMNarrator
from pipelines.evaluation.providers import (
    ChatMessage,
    CompletionRequest,
    CompletionResponse,
    ProviderError,
)


class FakeProvider:
    """Provider en mémoire : renvoie un contenu fixe, capture la dernière requête."""

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
        "cadre": "Une taverne enfumée au crépuscule.",
        "locuteur": {"nom": "Le Garde", "voix": "bourru"},
        "action_joueur": "Le joueur demande ce qu'il y a dans la cave.",
        "revealable": ["la cave sert d'entrepôt"],
        "withhold": ["qui a paye la rancon"],
        "form": {"registre": "familier", "budget": 1},
    }


def test_llm_narrator_returns_n_candidates() -> None:
    narrator = LLMNarrator(provider=FakeProvider("beat X"))
    out = narrator.narrate(_packet(), n=3)
    assert out == ["beat X", "beat X", "beat X"]


def test_llm_narrator_makes_n_calls() -> None:
    fake = FakeProvider()
    LLMNarrator(provider=fake).narrate(_packet(), n=4)
    assert len(fake.calls) == 4  # best-of-N = N générations


def test_llm_narrator_withhold_rendered_as_label() -> None:
    prompt = LLMNarrator(provider=FakeProvider()).render_packet(_packet())
    # L'intitulé withhold apparaît, mais sous la consigne « à TAIRE ».
    assert "qui a paye la rancon" in prompt
    assert "TAIRE" in prompt


def test_llm_narrator_prompt_contains_no_canon() -> None:
    # Fige l'invariant : le prompt ne contient QUE des champs du paquet.
    # Un secret jamais fourni ne doit pas apparaître.
    prompt = LLMNarrator(provider=FakeProvider()).render_packet(_packet())
    assert "le tresor est sous la troisieme dalle" not in prompt
    # Le prompt ne demande jamais de « tenir compte » du contenu d'un withhold.
    assert "tenir compte" not in prompt.lower()


def test_llm_narrator_provider_error_propagates() -> None:
    narrator = LLMNarrator(provider=ExplodingProvider())
    with pytest.raises(ProviderError):
        narrator.narrate(_packet(), n=2)


def test_narrate_endpoint_with_llm_swap() -> None:
    # Le swap d'injection marche bout-en-bout, router/contrat inchangés.
    app = create_app(tables=[], narrator=LLMNarrator(provider=FakeProvider("beat HTTP")))
    client = TestClient(app)
    body = {"schema_version": 1, "n": 2, "packet": _packet()}
    resp = client.post("/narrate", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert [c["text"] for c in data["candidates"]] == ["beat HTTP", "beat HTTP"]
    assert data["credits_spent"] == 2


def test_narrate_endpoint_provider_error_is_502() -> None:
    app = create_app(tables=[], narrator=LLMNarrator(provider=ExplodingProvider()))
    client = TestClient(app, raise_server_exceptions=False)
    body = {"schema_version": 1, "n": 2, "packet": _packet()}
    resp = client.post("/narrate", json=body)
    assert resp.status_code == 502  # pas de faux 200
