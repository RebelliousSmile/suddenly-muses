"""H5 (#89) — vérification RS256 via résolution JWK par `iss`, sans secret partagé.

Couvre la Phase 1 du plan `2026_07_06-89-narrate-muse-token-provisioning.md` :
- acceptation d'un token RS256 signé localement, `iss` servi via un
  `.well-known/jwks.json` simulé (`httpx.MockTransport`, pas de vrai réseau) ;
- rejet d'un `iss` hors liste blanche AVANT tout fetch réseau ;
- rejet d'un `kid` inconnu/tourné après exactement un refetch forcé ;
- régression `config._validate` : strict + JWKS sans secret OK, strict + rien refuse.
"""

from __future__ import annotations

import base64
import json
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from muses.narrate.issuer import MuseIssuer
from muses.narrate.jwks import JwksKeyResolver, make_jwks_key_lookup
from muses.narrate.session import JwtSessionVerifier, SessionTokenError

ISSUER = "muse.example"
KID = "key-1"


def _b64url_uint(value: int) -> str:
    length = (value.bit_length() + 7) // 8
    raw = value.to_bytes(length, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _generate_keypair() -> tuple[rsa.RSAPrivateKey, dict]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_numbers = private_key.public_key().public_numbers()
    jwk = {
        "kty": "RSA",
        "kid": KID,
        "use": "sig",
        "alg": "RS256",
        "n": _b64url_uint(public_numbers.n),
        "e": _b64url_uint(public_numbers.e),
    }
    return private_key, jwk


def _private_pem(private_key: rsa.RSAPrivateKey) -> bytes:
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _sign_token(
    private_key: rsa.RSAPrivateKey,
    *,
    kid: str = KID,
    iss: str = ISSUER,
    sub: str = "u1",
    ttl: int = 3600,
) -> str:
    payload = {"sub": sub, "iss": iss, "exp": int(time.time()) + ttl}
    return jwt.encode(
        payload, _private_pem(private_key), algorithm="RS256", headers={"kid": kid}
    )


class _CountingJwksTransport:
    """Sert `.well-known/jwks.json` pour un `iss` donné et compte les appels."""

    def __init__(self, jwks_document: dict) -> None:
        self.calls = 0
        self._document = jwks_document

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        assert request.url.path == "/.well-known/jwks.json"
        return httpx.Response(200, json=self._document)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def _never_called_transport() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("aucun appel réseau attendu (iss hors allowlist)")

    transport = httpx.MockTransport(handler)
    return httpx.Client(transport=transport)


def test_rs256_token_accepted_via_jwks_with_no_shared_secret() -> None:
    private_key, jwk = _generate_keypair()
    transport = _CountingJwksTransport({"keys": [jwk]})

    lookup = make_jwks_key_lookup(
        issuers=[ISSUER], http_client=transport.client()
    )
    verifier = JwtSessionVerifier(key_lookup=lookup, algorithms=["RS256"])

    token = _sign_token(private_key)
    claims = verifier.verify(token)

    assert claims.wallet_key == f"{ISSUER}/u1"
    assert claims.issuer == ISSUER
    assert transport.calls == 1


def test_unknown_issuer_rejected_without_network_call() -> None:
    private_key, _jwk = _generate_keypair()
    client = _never_called_transport()

    lookup = make_jwks_key_lookup(issuers=["other.example"], http_client=client)
    verifier = JwtSessionVerifier(key_lookup=lookup, algorithms=["RS256"])

    token = _sign_token(private_key, iss=ISSUER)  # iss hors allowlist
    with pytest.raises(SessionTokenError):
        verifier.verify(token)


def test_unknown_kid_triggers_single_refetch_then_fails_closed() -> None:
    private_key, jwk = _generate_keypair()
    transport = _CountingJwksTransport({"keys": [jwk]})

    resolver = JwksKeyResolver(issuers=[ISSUER], http_client=transport.client())
    verifier = JwtSessionVerifier(key_lookup=resolver.key_lookup, algorithms=["RS256"])

    # kid inconnu / tourné : jamais présent dans le document servi.
    token = _sign_token(private_key, kid="rotated-out")
    with pytest.raises(SessionTokenError):
        verifier.verify(token)

    # Un fetch initial + un refetch forcé = exactement 2 appels réseau.
    assert transport.calls == 2


def test_kid_rotation_recovers_after_warm_cache() -> None:
    """Un kid absent du cache chaud déclenche un refetch qui peut réussir."""
    private_key, jwk = _generate_keypair()
    other_private_key, other_jwk = _generate_keypair()
    other_jwk["kid"] = "key-2"

    documents = [{"keys": [jwk]}, {"keys": [jwk, other_jwk]}]
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        idx = min(calls["count"], len(documents) - 1)
        calls["count"] += 1
        return httpx.Response(200, json=documents[idx])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    resolver = JwksKeyResolver(issuers=[ISSUER], http_client=client)
    verifier = JwtSessionVerifier(key_lookup=resolver.key_lookup, algorithms=["RS256"])

    # 1er call : peuple le cache avec seulement `key-1` (1 fetch).
    ok = verifier.verify(_sign_token(private_key, kid=KID))
    assert ok.issuer == ISSUER
    assert calls["count"] == 1

    # 2e call : kid "key-2" absent du cache -> refetch forcé qui le trouve.
    ok2 = verifier.verify(_sign_token(other_private_key, kid="key-2"))
    assert ok2.issuer == ISSUER
    assert calls["count"] == 2


def test_https_only_issuer_rejected_for_plain_http_non_local() -> None:
    from muses.narrate.jwks import JwksResolutionError

    # `iss` déjà dans l'allowlist (on teste le gate https, pas l'allowlist).
    resolver = JwksKeyResolver(
        issuers=["http://insecure.example"], http_client=_never_called_transport()
    )
    with pytest.raises(JwksResolutionError):
        resolver.key_lookup({"kid": "any"}, {"iss": "http://insecure.example"})


# Régression `config._validate` (strict + JWKS sans secret / strict + rien) :
# voir `tests/muses/test_config.py` (fixture `clean_env` déjà présente, pas de
# duplication ici).


def test_issuer_round_trip_mint_and_verify_via_own_jwks() -> None:
    """Phase 2 — critère d'acceptation littéral : un token miné par
    `muses.narrate.issuer.MuseIssuer` est accepté par la vérification Phase 1
    (`JwtSessionVerifier` + `make_jwks_key_lookup`) contre le JWKS de ce même
    issuer, servi par le même `httpx.MockTransport` que le reste du fichier —
    aucun secret partagé, aucune clé privée côté vérification.
    """
    issuer = MuseIssuer.generate()
    transport = _CountingJwksTransport(issuer.jwks_document())

    lookup = make_jwks_key_lookup(issuers=[ISSUER], http_client=transport.client())
    verifier = JwtSessionVerifier(key_lookup=lookup, algorithms=["RS256"])

    token = issuer.mint_token("alice", ISSUER)
    claims = verifier.verify(token)

    assert claims.wallet_key == f"{ISSUER}/alice"
    assert claims.issuer == ISSUER
    assert transport.calls == 1
