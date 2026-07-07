"""H0 — Contrat du relais narrateur, importé depuis choix-narratifs.

Invariant #4 : le Hub ne redéfinit **pas** les types du paquet à la main. Il
charge le `schema.json` généré depuis `packet.rs` (CN) et valide les requêtes
`/narrate` contre lui via `jsonschema`. Toute dérive de schéma se corrige dans
CN d'abord, puis se répercute en remplaçant `contract/schema.json`.

La RACINE du schéma valide le corps de `POST /narrate` (`{ packet, n }`). Le
`schema_version` vit **dans** le paquet (`packet.schema_version`, const 1).
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

# Version de schéma attendue, alignée sur PACKET_SCHEMA_VERSION = 1 (packet.rs).
EXPECTED_PACKET_SCHEMA_VERSION = 1

_SCHEMA_PATH = Path(__file__).parent / "contract" / "schema.json"
# Reçu de provenance (Hub-B) : de quel commit CN provient `schema.json`.
_PROVENANCE_PATH = Path(__file__).parent / "contract" / "PROVENANCE.json"
_PLACEHOLDER_KEY = "x-suddenly-placeholder"

# Chemin (dans l'instance) du champ de version — sert à distinguer une
# incompatibilité de version (409) d'une simple requête malformée (400).
SCHEMA_VERSION_LOCATION = "packet/schema_version"


class PacketError(ValueError):
    """Le corps `/narrate` viole le contrat (schéma fermé).

    `location` = chemin du premier champ fautif dans l'instance (ex.
    `packet/schema_version`), pour le mapping fin des codes d'erreur.
    """

    def __init__(self, message: str, *, location: str = "(racine)") -> None:
        super().__init__(message)
        self.location = location


@lru_cache(maxsize=1)
def load_schema() -> dict:
    """Charge le `schema.json` versionné (mémoïsé)."""
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def schema_is_placeholder() -> bool:
    """True tant que le vrai schéma de CN n'a pas remplacé le placeholder."""
    return bool(load_schema().get(_PLACEHOLDER_KEY, False))


def declared_schema_version() -> int | None:
    """Version portée par le paquet du schéma (`$defs.ScenePacket.schema_version`)."""
    packet = load_schema().get("$defs", {}).get("ScenePacket", {})
    const = packet.get("properties", {}).get("schema_version", {}).get("const")
    return const if isinstance(const, int) else None


@lru_cache(maxsize=1)
def load_provenance() -> dict:
    """Charge le reçu de provenance du contrat (Hub-B), mémoïsé.

    Décrit de quel commit CN provient `schema.json`. Écrit automatiquement par
    `scripts/import_narrate_contract.sh` — jamais à la main.
    """
    return json.loads(_PROVENANCE_PATH.read_text(encoding="utf-8"))


def schema_sha256() -> str:
    """Hash SHA-256 du `schema.json` réellement présent sur le disque."""
    return hashlib.sha256(_SCHEMA_PATH.read_bytes()).hexdigest()


def provenance_matches_schema() -> bool:
    """True si le reçu décrit bien le `schema.json` courant (pas de dérive).

    Garde-fou : si quelqu'un édite `schema.json` sans repasser par le script
    d'import, le hash enregistré dans le reçu ne correspond plus — le reçu ment.
    """
    return load_provenance().get("schema_sha256") == schema_sha256()


@lru_cache(maxsize=1)
def _validator():
    # Sélectionne automatiquement le draft déclaré par `$schema` (2020-12 ici).
    from jsonschema.validators import validator_for

    schema = load_schema()
    cls = validator_for(schema)
    cls.check_schema(schema)
    return cls(schema)


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
        raise PacketError(f"{location}: {first.message}", location=location)
