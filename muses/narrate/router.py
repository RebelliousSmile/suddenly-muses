"""H1 — Endpoint `POST /narrate` du relais narrateur.

Cloisonné de `muses/api/server.py` (routes suggest/analyze) pour marquer la
frontière sémantique D-Hub-0 : ces routes servent CN, sont aveugles au canon,
et ne partagent que l'infra (app, rate-limit, plus tard auth/métrage).

Le corps est validé contre `schema.json` (jsonschema), **pas** via un modèle
Pydantic réécrit à la main — invariant #4.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from muses.narrate.narrator import Narrator
from muses.narrate.schema import PacketError, validate_request


class NarrateCandidate(BaseModel):
    text: str


class NarrateResponse(BaseModel):
    candidates: list[NarrateCandidate]
    credits_spent: int


def create_narrate_router(narrator: Narrator) -> APIRouter:
    """Construit le router `/narrate` branché sur un `Narrator` injecté."""
    router = APIRouter()

    @router.post("/narrate", response_model=NarrateResponse)
    async def narrate(request: Request) -> NarrateResponse:
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
        texts = narrator.narrate(body["packet"], n)
        # H3 : credits_spent deviendra le débit réel du portefeuille (≈ n).
        return NarrateResponse(
            candidates=[NarrateCandidate(text=t) for t in texts],
            credits_spent=n,
        )

    return router
