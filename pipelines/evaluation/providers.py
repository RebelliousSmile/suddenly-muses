"""Couche provider LLM (OpenAI-compatible) — réintroduite pour le relais /narrate.

⚠️ Cette couche avait été supprimée au pivot D01 (abandon LoRA / inférence LLM
générative en production). Elle est réintroduite **uniquement** pour le rôle
relais narrateur (D-Hub-0, D16-D18) : le Hub appelle un provider LLM pour le
compte de choix-narratifs (`POST /narrate`). Les routes `/v1/suggest|analyze`
restent **sans LLM** (tables curées + ML CPU-only) — voir `project_brief.md`.

Together, Fireworks et OpenRouter exposent tous une API OpenAI-compatible
`/chat/completions` : un seul client générique suffit, sélectionné par
`SUPPORTING_PROVIDER` + la clé d'environnement correspondante.

Client httpx en singleton avec timeouts explicites (cf. règle
`07-quality/perf-pivots-httpx.md`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import httpx

# LLM : la lecture peut être lente — read large, connect court.
DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0)


@dataclass
class ChatMessage:
    role: str
    content: str


@dataclass
class CompletionRequest:
    model: str
    messages: list[ChatMessage]
    temperature: float = 0.8
    max_tokens: int = 256


@dataclass
class CompletionResponse:
    content: str
    model: str
    raw: dict = field(default_factory=dict)


class ProviderError(RuntimeError):
    """Échec d'appel au provider LLM (réseau, 4xx/5xx, réponse inattendue)."""


@runtime_checkable
class Provider(Protocol):
    name: str

    def chat_completion(self, request: CompletionRequest) -> CompletionResponse: ...


# nom -> (URL chat/completions, variable d'env de la clé)
_ENDPOINTS: dict[str, tuple[str, str]] = {
    "together": ("https://api.together.xyz/v1/chat/completions", "TOGETHER_API_KEY"),
    "fireworks": ("https://api.fireworks.ai/inference/v1/chat/completions", "FIREWORKS_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1/chat/completions", "OPENROUTER_API_KEY"),
}

_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(
            timeout=DEFAULT_TIMEOUT,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _client


class OpenAICompatibleProvider:
    """Provider générique pour toute API OpenAI-compatible `/chat/completions`."""

    def __init__(
        self,
        name: str,
        url: str,
        api_key: str,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.name = name
        self._url = url
        self._api_key = api_key
        self._client = client or _get_client()

    def chat_completion(self, request: CompletionRequest) -> CompletionResponse:
        payload = {
            "model": request.model,
            "messages": [
                {"role": m.role, "content": m.content} for m in request.messages
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        try:
            resp = self._client.post(
                self._url,
                json=payload,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise ProviderError(f"{self.name}: {type(exc).__name__}: {exc}") from exc
        return CompletionResponse(content=content, model=request.model, raw=data)


def list_available_providers() -> list[str]:
    """Providers dont la clé d'environnement est présente."""
    return [name for name, (_url, env) in _ENDPOINTS.items() if os.environ.get(env)]


def get_provider(name: str | None = None) -> Provider:
    """Résout le provider depuis `SUPPORTING_PROVIDER` (ou `name`) + sa clé d'env.

    Lève `ProviderError` si le provider est inconnu ou si la clé manque — fail
    explicite plutôt qu'un appel qui partira sans auth.
    """
    name = name or os.environ.get("SUPPORTING_PROVIDER") or "together"
    if name not in _ENDPOINTS:
        raise ProviderError(
            f"provider inconnu : {name!r} (connus : {', '.join(_ENDPOINTS)})"
        )
    url, env = _ENDPOINTS[name]
    api_key = os.environ.get(env)
    if not api_key:
        raise ProviderError(f"clé API absente : définir {env} (provider {name})")
    return OpenAICompatibleProvider(name, url, api_key)
