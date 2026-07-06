"""T35 — Endpoints admin du service Muses.

`/v1/admin/coverage` : carte de couverture contextuelle (architecture-tables-
ml.md § Carte de couverture). Renvoie, par cellule peuplée, le nombre de
rows par niveau et la date de dernière contribution.

`/v1/admin/narrate/credit` (H5, #89, Phase 3, optionnel) : provisionnement
explicite de crédits Muse pour un `wallet_key`, réutilisant `WalletStore.
credit()` (`muses/narrate/wallet.py`). Monté uniquement quand un portefeuille
`/narrate` est configuré (`narrate_wallet` non `None`) — c'est le pendant
opérationnel du contrôle d'accès réel introduit par `default_grant=0` en
mode strict (D-89.2) : sans provisionnement, un token validement signé mais
inconnu du portefeuille reçoit 402, jamais de crédit gratuit.

Pour le MVP, l'auth admin est un placeholder (header `X-Admin-Token`
attendu et comparé à un secret). En production (M4), passera par auth
ActivityPub avec acteurs admin déclarés.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel

from muses.narrate.wallet import WalletStore
from muses.schemas.tags import AXIS_NAMES
from muses.tables.jsonl_io import iter_rows


@dataclass
class CoverageCell:
    """Comptes d'une cellule contextuelle."""

    tags: dict[str, list[str]]
    counts_by_level: dict[str, int] = field(default_factory=dict)
    distinct_contributors: int = 0
    last_contribution: str | None = None  # ISO timestamp


def _cell_key(tags: dict[str, list[str]]) -> tuple:
    """Clé immuable pour une cellule (tags normalisés)."""
    return tuple(
        (axis, tuple(sorted(tags.get(axis, []))))
        for axis in AXIS_NAMES
    )


def compute_coverage(tables: list[Path]) -> list[CoverageCell]:
    """Parcourt les tables et agrège la couverture par cellule.

    Une row est attribuée à sa cellule exacte (ses tags). On ne déplie
    pas les listes multi-valeurs : une row tagguée `situation: [combat,
    intrigue]` est dans une cellule distincte d'une row `situation:
    [combat]` seule.
    """
    cells: dict[tuple, CoverageCell] = {}
    contributors: dict[tuple, set[str]] = defaultdict(set)

    for table_path in tables:
        table_path = Path(table_path)
        if not table_path.exists():
            continue
        for row in iter_rows(table_path):
            tags_dict = {axis: list(getattr(row.tags, axis)) for axis in AXIS_NAMES}
            key = _cell_key(tags_dict)
            cell = cells.setdefault(key, CoverageCell(tags=tags_dict))
            cell.counts_by_level[row.level] = cell.counts_by_level.get(row.level, 0) + 1
            if row.user_id:
                contributors[key].add(row.user_id)
            ts = row.created_at.isoformat()
            if cell.last_contribution is None or ts > cell.last_contribution:
                cell.last_contribution = ts

    for key, cell in cells.items():
        cell.distinct_contributors = len(contributors[key])

    return list(cells.values())


class NarrateCreditRequest(BaseModel):
    """Corps du `POST /v1/admin/narrate/credit` — provisionnement H5 (#89)."""

    wallet_key: str
    amount: int


class NarrateCreditResponse(BaseModel):
    """Réponse du `POST /v1/admin/narrate/credit`."""

    wallet_key: str
    balance: int


def create_admin_router(
    *,
    tables: list[Path],
    admin_token: str | None = None,
    narrate_wallet: WalletStore | None = None,
) -> APIRouter:
    """Construit le router admin.

    `admin_token` peut être None en dev/tests : l'auth est alors un no-op
    (permet d'utiliser l'endpoint sans header). En prod il doit être défini.

    `narrate_wallet` (H5, #89, Phase 3, optionnel) : si fourni, monte
    `POST /narrate/credit` pour provisionner un `wallet_key` explicitement
    (mêmes garde-fous d'auth que `/coverage`). Absent → route non montée.
    """
    router = APIRouter(prefix="/v1/admin")

    def _check_admin(token: str | None = Header(None, alias="X-Admin-Token")) -> None:
        if admin_token is None:
            return
        if token != admin_token:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin token invalid or missing",
            )

    @router.get("/coverage", dependencies=[])
    def coverage(token: str | None = Header(None, alias="X-Admin-Token")) -> dict:
        _check_admin(token)
        cells = compute_coverage(tables)
        return {
            "cells": [
                {
                    "tags": c.tags,
                    "counts_by_level": c.counts_by_level,
                    "distinct_contributors": c.distinct_contributors,
                    "last_contribution": c.last_contribution,
                }
                for c in cells
            ],
            "total_cells": len(cells),
        }

    if narrate_wallet is not None:

        @router.post("/narrate/credit", response_model=NarrateCreditResponse)
        def narrate_credit(
            req: NarrateCreditRequest,
            token: str | None = Header(None, alias="X-Admin-Token"),
        ) -> NarrateCreditResponse:
            _check_admin(token)
            if req.amount < 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="amount must be >= 0",
                )
            new_balance = narrate_wallet.credit(req.wallet_key, req.amount)
            return NarrateCreditResponse(wallet_key=req.wallet_key, balance=new_balance)

    return router
