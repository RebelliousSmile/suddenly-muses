"""Gradio playground pour Suddenly AI Hub.

Trois onglets :
- Palette : test inline des 9 features de use-cases.md
- Banc A/B : comparaison aveugle de 2 modèles, vote, CSV
- Gateway : état live de muse.suddenly.social (/v1/models, /v1/health, /v1/stats)

Lancement :
    python -m apps.playground.app

Prérequis :
    pip install -e ".[playground]"
    SUPPORTING_PROVIDER=together TOGETHER_API_KEY=... (ou FIREWORKS_API_KEY=...)
"""

from __future__ import annotations

import json
import os
import random

import gradio as gr
import httpx

from pipelines.evaluation.providers import (
    ChatMessage,
    CompletionRequest,
    get_provider,
    list_available_providers,
)

from .features import FEATURES, Feature
from . import votes

_http_client = httpx.Client(
    timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=2.0),
    limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
)

GATEWAY_URL = os.environ.get("SUDDENLY_HUB_URL", "https://muse.suddenly.social")

DEFAULT_MODELS = [
    "Qwen/Qwen2.5-7B-Instruct",
    "mistralai/Mistral-7B-Instruct-v0.3",
    "mistralai/Mistral-Nemo-Instruct-2407",
    "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
]


def _provider():
    return get_provider()


def _run_completion(model: str, system: str, user: str, temperature: float, max_tokens: int) -> str:
    prov = _provider()
    req = CompletionRequest(
        model=model,
        messages=[ChatMessage(role="system", content=system), ChatMessage(role="user", content=user)],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    try:
        resp = prov.chat_completion(req)
        return resp.content
    except Exception as exc:
        return f"[erreur provider] {type(exc).__name__}: {exc}"


def _palette_card(feature: Feature):
    with gr.Group():
        gr.Markdown(
            f"### {feature.name}  \n"
            f"**Adapter cible :** `{feature.adapter}`  "
            f"**Muses :** {feature.muses}  "
            f"**Type :** {feature.kind}  "
            f"**Issue :** #{feature.issue}"
        )
        model = gr.Textbox(
            value=DEFAULT_MODELS[0],
            label="Modèle",
            info="ID Together/Fireworks (ou ID de ton LoRA hébergé)",
        )
        system = gr.Textbox(value=feature.system_prompt, label="System prompt", lines=3)
        user = gr.Textbox(value=feature.sample_user_prompt, label="User prompt", lines=6)
        temperature = gr.Slider(0.0, 1.5, value=0.7, step=0.05, label="Temperature")
        max_tokens = gr.Slider(64, 2048, value=512, step=64, label="Max tokens")
        output = gr.Textbox(label="Sortie", lines=8, interactive=False)
        btn = gr.Button("Tester", variant="primary")
        btn.click(_run_completion, inputs=[model, system, user, temperature, max_tokens], outputs=output)


def _build_palette_tab():
    with gr.Tab("Palette"):
        gr.Markdown(
            "Palette des 9 features Suddenly. Le bouton **Tester** appelle le provider "
            "configuré (`SUPPORTING_PROVIDER`) avec le modèle de ton choix — utile pour "
            "valider qu'un LoRA fraîchement uploadé sait répondre au gabarit attendu."
        )
        for f in FEATURES:
            _palette_card(f)


def _run_ab(
    model_a: str,
    model_b: str,
    system: str,
    user: str,
    temperature: float,
    max_tokens: int,
):
    """Retourne (réponse gauche, réponse droite, modèle gauche, modèle droit)
    avec ordre aléatoire pour vote aveugle."""
    swap = random.random() < 0.5
    left_model, right_model = (model_b, model_a) if swap else (model_a, model_b)
    left = _run_completion(left_model, system, user, temperature, max_tokens)
    right = _run_completion(right_model, system, user, temperature, max_tokens)
    return left, right, left_model, right_model


def _record_vote(
    vote: str,
    feature_adapter: str,
    model_left: str,
    model_right: str,
    prompt_user: str,
    response_left: str,
    response_right: str,
    note: str,
):
    if not model_left or not model_right:
        return "⚠ Génère d'abord une comparaison avant de voter."
    votes.append_vote(
        feature_adapter=feature_adapter or "(libre)",
        model_left=model_left,
        model_right=model_right,
        prompt=prompt_user,
        response_left=response_left,
        response_right=response_right,
        vote=vote,
        note=note,
    )
    return f"✓ Vote `{vote}` enregistré ({model_left} vs {model_right})."


def _refresh_scoreboard():
    scores = votes.aggregate_scores()
    if not scores:
        return "Aucun vote enregistré."
    rows = ["| Modèle | Victoires | Défaites | Égalités |", "|---|---:|---:|---:|"]
    for model, s in sorted(scores.items(), key=lambda kv: kv[1]["wins"], reverse=True):
        rows.append(f"| `{model}` | {s['wins']} | {s['losses']} | {s['ties']} |")
    return "\n".join(rows)


def _build_ab_tab():
    with gr.Tab("Banc A/B"):
        gr.Markdown(
            "Compare deux modèles **en aveugle** sur le même prompt. L'ordre gauche/droite "
            "est randomisé. Le vote est persisté dans `data/playground/votes.csv`."
        )
        feature_choices = ["(libre)"] + [f.adapter for f in FEATURES]
        with gr.Row():
            feature_dd = gr.Dropdown(
                choices=feature_choices,
                value="(libre)",
                label="Feature/Adapter de référence",
            )
            model_a = gr.Textbox(value=DEFAULT_MODELS[0], label="Modèle A")
            model_b = gr.Textbox(value=DEFAULT_MODELS[1], label="Modèle B")
        with gr.Row():
            system = gr.Textbox(label="System prompt", lines=3, value="Tu es un assistant d'écriture RP en français.")
            user = gr.Textbox(label="User prompt", lines=6)
        with gr.Row():
            temperature = gr.Slider(0.0, 1.5, value=0.7, step=0.05, label="Temperature")
            max_tokens = gr.Slider(64, 2048, value=512, step=64, label="Max tokens")

        run_btn = gr.Button("Générer la comparaison", variant="primary")

        with gr.Row():
            left_out = gr.Textbox(label="Gauche", lines=10, interactive=False)
            right_out = gr.Textbox(label="Droite", lines=10, interactive=False)

        left_model_state = gr.State("")
        right_model_state = gr.State("")

        run_btn.click(
            _run_ab,
            inputs=[model_a, model_b, system, user, temperature, max_tokens],
            outputs=[left_out, right_out, left_model_state, right_model_state],
        )

        with gr.Row():
            vote_left = gr.Button("◀ Gauche gagne")
            vote_tie = gr.Button("= Égalité")
            vote_right = gr.Button("Droite gagne ▶")
        note = gr.Textbox(label="Note (optionnel)", lines=1)
        vote_status = gr.Markdown()

        def _make_vote(direction):
            def _cb(adapter, lm, rm, p, l, r, n):
                msg = _record_vote(direction, adapter, lm, rm, p, l, r, n)
                return msg, _refresh_scoreboard()
            return _cb

        scoreboard = gr.Markdown(_refresh_scoreboard())

        vote_left.click(
            _make_vote("left"),
            inputs=[feature_dd, left_model_state, right_model_state, user, left_out, right_out, note],
            outputs=[vote_status, scoreboard],
        )
        vote_tie.click(
            _make_vote("tie"),
            inputs=[feature_dd, left_model_state, right_model_state, user, left_out, right_out, note],
            outputs=[vote_status, scoreboard],
        )
        vote_right.click(
            _make_vote("right"),
            inputs=[feature_dd, left_model_state, right_model_state, user, left_out, right_out, note],
            outputs=[vote_status, scoreboard],
        )


def _fetch_gateway() -> str:
    parts = [f"### Gateway : `{GATEWAY_URL}`\n"]
    models_resp_text: str | None = None
    for endpoint in ("/v1/health", "/v1/models", "/v1/stats"):
        try:
            resp = _http_client.get(f"{GATEWAY_URL}{endpoint}")
            parts.append(f"**{endpoint}** → HTTP {resp.status_code}")
            parts.append(f"```json\n{resp.text}\n```")
            if endpoint == "/v1/models" and resp.is_success:
                models_resp_text = resp.text
        except httpx.RequestError as exc:
            parts.append(f"**{endpoint}** → erreur : `{exc}`")
    parts.append("\n---")
    parts.append("**Couverture de la palette :**")
    adapters: set[str] = set()
    try:
        if models_resp_text is None:
            raise ValueError("La requête /v1/models a échoué ou retourné une erreur HTTP")
        data = json.loads(models_resp_text)
        for m in data.get("data", []):
            adapters.update(m.get("available_adapters", []))
    except (ValueError, json.JSONDecodeError) as exc:
        parts.append(f"_Impossible de récupérer les adapters : {exc}_")
        return "\n".join(parts)
    for f in FEATURES:
        target = f.adapter.split()[0]
        mark = "✅" if target in adapters else "⬜"
        parts.append(f"- {mark} `{target}` — {f.name} (#{f.issue})")
    return "\n".join(parts)


def _build_gateway_tab():
    with gr.Tab("Gateway"):
        out = gr.Markdown()
        btn = gr.Button("Rafraîchir", variant="primary")
        btn.click(_fetch_gateway, outputs=out)
        gr.Markdown(
            "_Note : `/v1/chat/completions` exige une signature HTTP ActivityPub, donc "
            "non testable depuis ce playground. Utilise les onglets Palette / Banc A/B "
            "(qui passent par les providers Together/Fireworks)._"
        )


def build_app() -> gr.Blocks:
    available = ", ".join(list_available_providers())
    with gr.Blocks(title="Suddenly AI Playground", theme=gr.themes.Soft()) as demo:
        gr.Markdown(
            f"# 🎭 Suddenly AI Playground  \n"
            f"Providers dispos : `{available}` — sélection via `SUPPORTING_PROVIDER` "
            f"ou auto-détection. Gateway showcase : `{GATEWAY_URL}`."
        )
        _build_palette_tab()
        _build_ab_tab()
        _build_gateway_tab()
    return demo


if __name__ == "__main__":
    build_app().launch()
