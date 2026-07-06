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


class JwtSessionVerifier:
    """Vérifie réellement le JWT (signature + exp).

    - HS256 : `key` = secret partagé (dev/CI).
    - RS256 : `key` = clé publique PEM (prod ; en attendant la résolution JWK
      par `iss` décrite dans D18, à brancher via `key_lookup`).
    """

    def __init__(
        self,
        *,
        key: str | bytes,
        algorithms: list[str] | None = None,
        issuers: list[str] | None = None,
        leeway_seconds: int = 10,
    ) -> None:
        self._key = key
        self._algorithms = algorithms or ["HS256"]
        self._issuers = set(issuers) if issuers else None
        self._leeway = leeway_seconds

    def verify(self, token: str) -> SessionClaims:
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
