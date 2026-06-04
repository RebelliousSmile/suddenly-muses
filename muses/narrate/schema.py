"""H0 — Contrat du relais narrateur, importé depuis choix-narratifs.

Invariant #4 : le Hub ne redéfinit **pas** les types du paquet à la main. Il
charge le `schema.json` généré depuis `packet.rs` (CN) et valide les requêtes
`/narrate` contre lui via `jsonschema`. Toute dérive de schéma se corrige dans
CN d'abord, puis se répercute en remplaçant `contract/schema.json`.

Le `schema.json` présent est un **placeholder** tant que le vrai schéma de CN
n'a pas été déposé (cf. `schema_is_placeholder`). Le test garde-couture le
signale (xfail) sans bloquer la boucle H1.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

# Version de schéma attendue, alignée sur PACKET_SCHEMA_VERSION = 1 (packet.rs).
EXPECTED_PACKET_SCHEMA_VERSION = 1

_SCHEMA_PATH = Path(__file__).parent / "contract" / "schema.json"
_PLACEHOLDER_KEY = "x-suddenly-placeholder"


class PacketError(ValueError):
    """Le corps `/narrate` viole le contrat (schéma fermé). → HTTP 422."""


@lru_cache(maxsize=1)
def load_schema() -> dict:
    """Charge le `schema.json` versionné (mémoïsé)."""
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def schema_is_placeholder() -> bool:
    """True tant que le vrai schéma de CN n'a pas remplacé le placeholder."""
    return bool(load_schema().get(_PLACEHOLDER_KEY, False))


def declared_schema_version() -> int | None:
    """Version portée par le `schema.json` (via `properties.schema_version.const`)."""
    const = load_schema().get("properties", {}).get("schema_version", {}).get("const")
    return const if isinstance(const, int) else None


@lru_cache(maxsize=1)
def _validator():
    # Import différé : jsonschema fait partie de l'extra [api].
    from jsonschema import Draft7Validator

    return Draft7Validator(load_schema())


def validate_request(body: object) -> None:
    """Valide un corps `/narrate` contre le contrat. Lève `PacketError` sinon.

    Le schéma est fermé (`additionalProperties: false` à tous les niveaux) :
    un champ inattendu, une `schema_version` fausse ou un `n` hors bornes
    déclenchent une erreur — « le schéma EST le mur ».
    """
    if not isinstance(body, dict):
        raise PacketError("le corps doit être un objet JSON")
    errors = sorted(_validator().iter_errors(body), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        location = "/".join(str(p) for p in first.path) or "(racine)"
        raise PacketError(f"{location}: {first.message}")
