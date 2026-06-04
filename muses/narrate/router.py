"""H1 — Endpoint `POST /narrate` du relais narrateur.

Cloisonné de `muses/api/server.py` (routes suggest/analyze) pour marquer la
frontière sémantique D-Hub-0 : ces routes servent CN, sont aveugles au canon,
et ne partagent que l'infra (app, rate-limit, plus tard auth/métrage).

Le corps est validé contre `schema.json` (jsonschema), **pas** via un modèle
Pydantic réécrit à la main — invariant #4.
"""

from __future__ import annotations

import json
from typing import Callable

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from muses.narrate.narrator import Narrator
from muses.narrate.schema import PacketError, validate_request
from muses.narrate.session import SessionClaims
from muses.narrate.wallet import WalletStore


class NarrateCandidate(BaseModel):
    text: str


class NarrateResponse(BaseModel):
    candidates: list[NarrateCandidate]
    credits_spent: int


def create_narrate_router(
    narrator: Narrator,
    *,
    session_auth: Callable[[Request], SessionClaims] | None = None,
    wallet: WalletStore | None = None,
) -> APIRouter:
    """Construit le router `/narrate`.

    - `session_auth` (H3) : dependency qui vérifie le token de session et résout
      l'identité. `None` → pas d'auth (H1/H2, dev).
    - `wallet` (H3) : portefeuille Muse pour le métrage. `None` → pas de débit,
      `credits_spent = n`.
    """
    router = APIRouter()

    @router.post("/narrate", response_model=NarrateResponse)
    async def narrate(request: Request) -> NarrateResponse:
        # 1. Auth (H3) — avant tout travail ; 401 si token absent/invalide.
        claims = session_auth(request) if session_auth is not None else None

        # 2. JSON + contrat fermé (H0/H1).
        try:
            body = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise HTTPException(status_code=422, detail="corps illisible : JSON invalide")
        try:
            validate_request(body)
        except PacketError as exc:
            # Le schéma EST le mur : champ inconnu / version fausse / n hors bornes.
            raise HTTPException(status_code=422, detail=f"PacketError: {exc}")

        n = body["n"]
        effective_n = n

        # 3. Métrage (H3) — levier portefeuille bas, 402 si vide.
        wallet_key = ""
        if wallet is not None:
            wallet_key = claims.wallet_key if claims is not None else "_anonymous"
            balance = wallet.balance(wallet_key)
            if balance <= 0:
                raise HTTPException(status_code=402, detail="portefeuille Muse vide")
            if balance < n:
                effective_n = 1  # levier : portefeuille bas → forcer n=1

        # 4. Génération best-of-N. I/O bloquante (LLMNarrator) → threadpool
        #    (règle perf-pivots-fastapi §9). ProviderError → 502 via create_app ;
        #    le débit ci-dessous n'a alors pas lieu (aucune unité perdue).
        texts = await run_in_threadpool(narrator.narrate, body["packet"], effective_n)

        # 5. Débit APRÈS génération réussie.
        spent = effective_n
        if wallet is not None:
            wallet.debit(wallet_key, spent)

        return NarrateResponse(
            candidates=[NarrateCandidate(text=t) for t in texts],
            credits_spent=spent,
        )

    return router
