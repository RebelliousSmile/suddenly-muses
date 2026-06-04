"""Relais narrateur best-of-N pour choix-narratifs (D-Hub-0).

Famille de routes distincte de `/v1/suggest|analyze/*` : aveugle au canon,
sert CN, partage l'infra Hub sans partager la sémantique.
"""

from muses.narrate.narrator import CannedNarrator, Narrator
from muses.narrate.router import (
    NarrateCandidate,
    NarrateResponse,
    create_narrate_router,
)
from muses.narrate.schema import (
    EXPECTED_PACKET_SCHEMA_VERSION,
    PacketError,
    declared_schema_version,
    load_schema,
    schema_is_placeholder,
    validate_request,
)

__all__ = [
    "CannedNarrator",
    "Narrator",
    "NarrateCandidate",
    "NarrateResponse",
    "create_narrate_router",
    "EXPECTED_PACKET_SCHEMA_VERSION",
    "PacketError",
    "declared_schema_version",
    "load_schema",
    "schema_is_placeholder",
    "validate_request",
]
