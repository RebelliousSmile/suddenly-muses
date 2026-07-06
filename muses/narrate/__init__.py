"""Relais narrateur best-of-N pour choix-narratifs (D-Hub-0).

Famille de routes distincte de `/v1/suggest|analyze/*` : aveugle au canon,
sert CN, partage l'infra Hub sans partager la sémantique.
"""

from muses.narrate.issuer import (
    MuseIssuer,
    build_jwks_document,
    generate_keypair,
    mint_token,
)
from muses.narrate.jwks import (
    JwksKeyResolver,
    JwksResolutionError,
    make_jwks_key_lookup,
)
from muses.narrate.narrator import CannedNarrator, LLMNarrator, Narrator
from muses.narrate.router import create_narrate_router
from muses.narrate.schema import (
    EXPECTED_PACKET_SCHEMA_VERSION,
    PacketError,
    declared_schema_version,
    load_schema,
    schema_is_placeholder,
    validate_request,
)
from muses.narrate.session import (
    JwtSessionVerifier,
    SessionClaims,
    SessionTokenError,
    SessionVerifier,
    StubSessionVerifier,
    make_session_dependency,
)
from muses.narrate.wallet import WalletStore

__all__ = [
    "CannedNarrator",
    "LLMNarrator",
    "Narrator",
    "create_narrate_router",
    "EXPECTED_PACKET_SCHEMA_VERSION",
    "PacketError",
    "declared_schema_version",
    "load_schema",
    "schema_is_placeholder",
    "validate_request",
    "JwtSessionVerifier",
    "SessionClaims",
    "SessionTokenError",
    "SessionVerifier",
    "StubSessionVerifier",
    "make_session_dependency",
    "WalletStore",
    "JwksKeyResolver",
    "JwksResolutionError",
    "make_jwks_key_lookup",
    "MuseIssuer",
    "build_jwks_document",
    "generate_keypair",
    "mint_token",
]
