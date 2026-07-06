"""H5 — résolution de la clé de vérification par `iss` via JWK (D18).

Complète `session.py` : `JwtSessionVerifier` peut être construit avec un
`key_lookup` au lieu d'un secret statique. Ce module fournit ce `key_lookup`
pour le cas asymétrique fédéré : chaque instance Muse publie ses clés
publiques à `<iss>/.well-known/jwks.json` (format JWK standard), le Hub les
résout à la volée par `iss` puis `kid`, SANS jamais détenir de clé privée ni
de secret partagé.

Sécurité (cf. risk register du plan #89) :
- `iss` allowlist (mêmes semantics que `JwtSessionVerifier.issuers`) vérifiée
  AVANT tout fetch réseau — pas de SSRF sur un domaine arbitraire.
- https-only, sauf `localhost`/`127.0.0.1` (tests / dev local uniquement).
- Cache TTL par `iss` (mêmes idiomes que `muses/api/signature.py:HttpKeyResolver`) ;
  sur `kid` inconnu, un seul refetch forcé avant échec fermé (401).
- Client httpx singleton, timeouts explicites (règle `perf-pivots-httpx` §9) ;
  toute cette résolution est synchrone et tourne dans un threadpool côté
  appelant (`router.py`), jamais dans l'event loop.
"""

from __future__ import annotations

import json
import time
from typing import Callable
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException, status
from jwt.algorithms import RSAAlgorithm


class JwksResolutionError(HTTPException):
    """Échec de résolution de clé JWK (issuer/kid inconnu, réseau, format) — toujours 401."""

    def __init__(self, detail: str):
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def _issuer_jwks_url(iss: str) -> str:
    """Construit l'URL `.well-known/jwks.json` depuis un `iss`.

    `iss` peut être un domaine nu (`muse.example` -> `https://muse.example/...`)
    ou déjà une URL complète (utilisée telle quelle comme base).
    """
    if iss.startswith("http://") or iss.startswith("https://"):
        base = iss.rstrip("/")
    else:
        base = f"https://{iss}"
    return f"{base}/.well-known/jwks.json"


def _is_https_or_local(iss: str) -> bool:
    """https obligatoire, sauf localhost/127.0.0.1 (dev/tests)."""
    if iss.startswith("https://"):
        return True
    if iss.startswith("http://"):
        host = urlsplit(iss).hostname or ""
        return host in ("localhost", "127.0.0.1")
    # Domaine nu : `_issuer_jwks_url` force https, donc toujours sûr.
    return True


class JwksKeyResolver:
    """Résout `(header, claims non vérifiées) -> (clé publique, algorithme)`.

    Un seul resolver couvre tous les `iss` autorisés : le cache est tenu par
    `iss`, la liste blanche filtre avant tout accès réseau.
    """

    def __init__(
        self,
        *,
        issuers: list[str] | None,
        timeout_seconds: float = 5.0,
        cache_ttl_seconds: float = 3600.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        if not issuers:
            # Revue de code #89 (minor) : défense en profondeur — `config._validate`
            # exige déjà une allowlist quand JWKS est activé, mais le resolver ne
            # doit jamais devenir un no-op silencieux (fetch de n'importe quel
            # `iss`, SSRF) si construit directement hors de ce chemin de config.
            raise ValueError(
                "JwksKeyResolver requiert une allowlist `issuers` non vide — "
                "sans elle, la résolution JWK fetch n'importe quel domaine passé "
                "en iss (risque SSRF)."
            )
        self._issuers = set(issuers)
        self.cache_ttl_seconds = cache_ttl_seconds
        self._client = http_client or httpx.Client(
            timeout=timeout_seconds, follow_redirects=False,
        )
        # iss -> (fetched_at_monotonic, {kid: clé publique RSA})
        self._cache: dict[str, tuple[float, dict[str, object]]] = {}

    def _check_allowlist(self, iss: str) -> None:
        if self._issuers is not None and iss not in self._issuers:
            raise JwksResolutionError(f"issuer non autorisé: {iss!r}")

    def _fetch_keys(self, iss: str) -> dict[str, object]:
        if not _is_https_or_local(iss):
            raise JwksResolutionError(
                f"issuer non-https refusé (https requis, sauf localhost): {iss!r}"
            )
        url = _issuer_jwks_url(iss)
        try:
            resp = self._client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise JwksResolutionError(f"JWKS injoignable pour {iss!r}: {exc}") from exc

        try:
            document = resp.json()
        except ValueError as exc:
            raise JwksResolutionError(f"JWKS illisible (JSON invalide) pour {iss!r}: {exc}") from exc

        keys: dict[str, object] = {}
        for jwk in document.get("keys", []) if isinstance(document, dict) else []:
            kid = jwk.get("kid")
            if not kid or jwk.get("kty") != "RSA":
                continue
            try:
                keys[kid] = RSAAlgorithm.from_jwk(json.dumps(jwk))
            except (ValueError, TypeError, KeyError):
                continue  # entrée JWK malformée — ignorée, pas fatale pour les autres kid
        return keys

    def _keys_for_issuer(self, iss: str, *, force_refetch: bool = False) -> dict[str, object]:
        now = time.monotonic()
        cached = self._cache.get(iss)
        if not force_refetch and cached is not None and (now - cached[0]) < self.cache_ttl_seconds:
            return cached[1]
        keys = self._fetch_keys(iss)
        self._cache[iss] = (now, keys)
        return keys

    def key_lookup(self, header: dict, unverified_claims: dict) -> tuple[object, str]:
        iss = unverified_claims.get("iss")
        if not iss:
            raise JwksResolutionError("token sans claim iss")
        self._check_allowlist(iss)

        kid = header.get("kid")
        if not kid:
            raise JwksResolutionError("en-tête token sans kid")

        keys = self._keys_for_issuer(iss)
        key = keys.get(kid)
        if key is None:
            # Rotation possible côté instance émettrice : un seul refetch forcé
            # avant d'échouer fermé (évite un cache figé sur un `kid` retiré).
            keys = self._keys_for_issuer(iss, force_refetch=True)
            key = keys.get(kid)
        if key is None:
            raise JwksResolutionError(f"kid {kid!r} introuvable pour issuer {iss!r}")
        return key, "RS256"

    def __call__(self, header: dict, unverified_claims: dict) -> tuple[object, str]:
        return self.key_lookup(header, unverified_claims)


def make_jwks_key_lookup(
    *,
    issuers: list[str] | None,
    timeout_seconds: float = 5.0,
    cache_ttl_seconds: float = 3600.0,
    http_client: httpx.Client | None = None,
) -> Callable[[dict, dict], tuple[object, str]]:
    """Factory : construit le `key_lookup` branché sur `JwtSessionVerifier`."""
    resolver = JwksKeyResolver(
        issuers=issuers,
        timeout_seconds=timeout_seconds,
        cache_ttl_seconds=cache_ttl_seconds,
        http_client=http_client,
    )
    return resolver.key_lookup
