"""H1/H3 — Endpoint `POST /narrate` du relais narrateur.

Cloisonné de `muses/api/server.py` (routes suggest/analyze) pour marquer la
frontière sémantique D-Hub-0 : ces routes servent CN, sont aveugles au canon,
et ne partagent que l'infra (app, rate-limit, auth/métrage).

Conforme au contrat de couture CN (`contract/schema.json`) :
- requête `{ packet, n }`, validée contre le schéma (jsonschema), pas via un
  modèle Pydantic réécrit à la main — invariant #4 ;
- réponse 200 `{ candidates: [str], schema_version: 1 }` avec **exactement `n`**
  candidats (le Hub ne tronque pas — le verifier reste côté CN) ;
- erreurs typées `{ error, detail, retriable }` :
  `unauthorized` 401 · `quota_exhausted` 402 · `bad_request` 400 ·
  `schema_incompatible` 409 · `provider_error` 502.

Le métrage (débit portefeuille) passe en en-tête `X-Muses-Credits-Spent` pour ne
pas polluer le corps fermé attendu par CN.
"""

from __future__ import annotations

import json
from typing import Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from muses.narrate.narrator import Narrator
from muses.narrate.schema import (
    SCHEMA_VERSION_LOCATION,
    PacketError,
    validate_request,
)
from muses.narrate.session import SessionClaims
from muses.narrate.wallet import WalletStore
from pipelines.evaluation.providers import ProviderError


def _error(status: int, error: str, detail: str, *, retriable: bool = False) -> JSONResponse:
    """Corps d'erreur typé conforme à `NarrateError` du contrat CN."""
    return JSONResponse(
        status_code=status,
        content={"error": error, "detail": detail, "retriable": retriable},
    )


def packet_with_language(body: dict) -> dict:
    """Résout le placement du futur champ CN `language` (Hub-C #93).

    Prépare les DEUX placements possibles sans en présumer (le narrateur ne voit
    que le paquet) :
    - `language` au niveau enveloppe (`NarrateRequest.language`) → recopié dans
      le paquet, sans muter l'original ;
    - `language` déjà dans le paquet → laissé tel quel.
    No-op tant que le schéma fermé vendorisé n'autorise aucun des deux (`body`
    ne peut alors pas le porter). Le champ décrit la forme, pas le canon.
    """
    packet = body["packet"]
    if "language" in body and "language" not in packet:
        return {**packet, "language": body["language"]}
    return packet


def create_narrate_router(
    narrator: Narrator,
    *,
    session_auth: Callable[[Request], SessionClaims] | None = None,
    wallet: WalletStore | None = None,
) -> APIRouter:
    """Construit le router `/narrate`.

    - `session_auth` (H3) : callable qui vérifie le token de session et résout
      l'identité. `None` → pas d'auth (H1/H2, dev).
    - `wallet` (H3) : portefeuille Muse pour le métrage. `None` → pas de débit.
    """
    router = APIRouter()

    @router.post("/narrate")
    async def narrate(request: Request) -> JSONResponse:
        # 1. Auth (H3) — avant tout travail.
        claims: SessionClaims | None = None
        if session_auth is not None:
            try:
                # session_auth peut résoudre une clé JWK par réseau (H5) — reste
                # synchrone, donc dispatché en threadpool pour ne pas bloquer
                # l'event loop (règle perf-pivots-fastapi §9).
                claims = await run_in_threadpool(session_auth, request)
            except HTTPException as exc:
                return _error(401, "unauthorized", str(exc.detail))

        # 2. JSON + contrat fermé (H0/H1). Le schéma EST le mur.
        try:
            body = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            return _error(400, "bad_request", "corps illisible : JSON invalide")
        try:
            validate_request(body)
        except PacketError as exc:
            if exc.location == SCHEMA_VERSION_LOCATION:
                return _error(409, "schema_incompatible", str(exc))
            return _error(400, "bad_request", str(exc))

        n = body["n"]

        # 3. Métrage (H3) — le contrat exige EXACTEMENT n candidats, donc pas de
        #    levier « n=1 » : si le portefeuille ne couvre pas n, on refuse (402).
        wallet_key = ""
        if wallet is not None:
            wallet_key = claims.wallet_key if claims is not None else "_anonymous"
            if wallet.balance(wallet_key) < n:
                return _error(
                    402, "quota_exhausted",
                    f"portefeuille Muse insuffisant pour n={n}",
                )

        # 4. Génération best-of-N. I/O bloquante (LLMNarrator) → threadpool
        #    (règle perf-pivots-fastapi §9). Aucun débit sur erreur provider.
        #    `packet_with_language` prépare le champ CN `language` (Hub-C #93) ;
        #    no-op tant que le schéma vendorisé ne l'autorise pas.
        try:
            texts = await run_in_threadpool(
                narrator.narrate, packet_with_language(body), n
            )
        except ProviderError as exc:
            return _error(502, "provider_error", str(exc), retriable=True)

        # 5. Débit APRÈS génération réussie.
        if wallet is not None:
            wallet.debit(wallet_key, n)

        response = JSONResponse(content={"candidates": texts, "schema_version": 1})
        response.headers["X-Muses-Credits-Spent"] = str(n)
        return response

    return router
