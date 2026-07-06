"""H3 — Auth par token de session pour le relais `/narrate` (D18).

Distinct de la signature ActivityPub plein-pot (`muses/api/signature.py`) qui
reste pour `/v1/suggest|analyze`. Ici : un JWT court émis par une instance Muse
(`sub` = user_id, `iss` = domaine Muse), que le Hub vérifie — idéalement via le
JWK endpoint de l'instance émettrice (D18). Stateless côté Hub.

Deux modes, en miroir de `signature.py` :
- `StubSessionVerifier` : décode les claims SANS vérifier la signature (dev/local).
- `JwtSessionVerifier` : vérifie réellement (HS256 secret partagé pour dev/CI,
  ou RS256 avec clé publique / JWK en prod).

Le `wallet_key` dérivé (`iss/sub`) indexe le portefeuille Muse (cf. `wallet.py`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

import jwt
from fastapi import HTTPException, Request, status


@dataclass
class SessionClaims:
    """Identité résolue depuis un token de session vérifié."""

    wallet_key: str
    user_id: str
    issuer: str
    raw: dict = field(default_factory=dict)


class SessionTokenError(HTTPException):
    """Token absent / malformé / invalide — toujours 401."""

    def __init__(self, detail: str):
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


class SessionVerifier(Protocol):
    def verify(self, token: str) -> SessionClaims: ...


def _claims_from_payload(payload: dict) -> SessionClaims:
    iss = payload.get("iss")
    sub = payload.get("sub")
    if not iss or not sub:
        raise SessionTokenError("token sans claims iss/sub")
    return SessionClaims(
        wallet_key=f"{iss}/{sub}",
        user_id=str(sub),
        issuer=str(iss),
        raw=payload,
    )


class StubSessionVerifier:
    """Décode les claims sans vérifier la signature — dev/local uniquement."""

    def verify(self, token: str) -> SessionClaims:
        try:
            payload = jwt.decode(token, options={"verify_signature": False})
        except jwt.PyJWTError as exc:
            raise SessionTokenError(f"token non décodable: {exc}") from exc
        return _claims_from_payload(payload)


KeyLookup = Callable[[dict, dict], "tuple[str | bytes, str]"]
"""Résout `(header non vérifié, claims non vérifiées) -> (clé, algorithme)`.

Appelé APRÈS un décodage non-vérifié (pour lire `kid`/`iss`) et AVANT le
`jwt.decode` réel qui vérifie la signature. Doit être synchrone : le fetch
réseau éventuel (résolution JWK par `iss`, cf. `muses/narrate/jwks.py`) tourne
dans un threadpool côté appelant (`router.py`), pas dans l'event loop.
"""


class JwtSessionVerifier:
    """Vérifie réellement le JWT (signature + exp).

    Deux sources de clé mutuellement exclusives :
    - `key` : secret partagé HS256 (dev/CI) ou clé publique PEM statique.
    - `key_lookup` : résolution dynamique par `iss`/`kid` (JWK, D18) — voir
      `muses/narrate/jwks.py:make_jwks_key_lookup`. Prioritaire sur `key` si
      les deux sont fournis.
    """

    def __init__(
        self,
        *,
        key: str | bytes | None = None,
        key_lookup: KeyLookup | None = None,
        algorithms: list[str] | None = None,
        issuers: list[str] | None = None,
        leeway_seconds: int = 10,
    ) -> None:
        if key is None and key_lookup is None:
            raise ValueError(
                "JwtSessionVerifier requiert soit `key` (secret/PEM statique) "
                "soit `key_lookup` (résolution JWK par iss)."
            )
        self._key = key
        self._key_lookup = key_lookup
        self._algorithms = algorithms or ["HS256"]
        self._issuers = set(issuers) if issuers else None
        self._leeway = leeway_seconds

    def verify(self, token: str) -> SessionClaims:
        if self._key_lookup is not None:
            return self._verify_with_lookup(token)
        return self._verify_with_static_key(token)

    def _verify_with_static_key(self, token: str) -> SessionClaims:
        try:
            payload = jwt.decode(
                token,
                self._key,
                algorithms=self._algorithms,
                leeway=self._leeway,
                options={"require": ["sub", "iss", "exp"]},
            )
        except jwt.PyJWTError as exc:
            raise SessionTokenError(f"token invalide: {exc}") from exc
        claims = _claims_from_payload(payload)
        if self._issuers is not None and claims.issuer not in self._issuers:
            raise SessionTokenError(f"issuer non autorisé: {claims.issuer}")
        return claims

    def _verify_with_lookup(self, token: str) -> SessionClaims:
        assert self._key_lookup is not None
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise SessionTokenError(f"en-tête token illisible: {exc}") from exc
        try:
            unverified_claims = jwt.decode(token, options={"verify_signature": False})
        except jwt.PyJWTError as exc:
            raise SessionTokenError(f"token non décodable: {exc}") from exc

        try:
            key, algorithm = self._key_lookup(header, unverified_claims)
        except SessionTokenError:
            raise
        except Exception as exc:  # résolveur JWKS (réseau, kid/iss inconnus, ...)
            raise SessionTokenError(f"résolution de clé impossible: {exc}") from exc

        if algorithm not in self._algorithms:
            raise SessionTokenError(f"algorithme {algorithm!r} non autorisé")

        try:
            payload = jwt.decode(
                token,
                key,
                algorithms=[algorithm],
                leeway=self._leeway,
                options={"require": ["sub", "iss", "exp"]},
            )
        except jwt.PyJWTError as exc:
            raise SessionTokenError(f"token invalide: {exc}") from exc

        claims = _claims_from_payload(payload)
        if self._issuers is not None and claims.issuer not in self._issuers:
            raise SessionTokenError(f"issuer non autorisé: {claims.issuer}")
        return claims


def make_session_dependency(
    verifier: SessionVerifier,
) -> Callable[[Request], SessionClaims]:
    """Construit la dependency d'auth : exige `Authorization: Bearer <jwt>`."""

    def _dep(request: Request) -> SessionClaims:
        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            raise SessionTokenError("en-tête Authorization: Bearer <token> requis")
        token = header[7:].strip()
        if not token:
            raise SessionTokenError("token vide")
        return verifier.verify(token)

    return _dep
