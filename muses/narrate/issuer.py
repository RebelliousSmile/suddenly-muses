"""H5 (#89, Phase 2) — autorité d'émission côté instance (D18, D-89.1).

Ce module tient la clé privée RSA. C'est le SEUL endroit de ce dépôt qui en
détient une : le Hub (`muses/api/*`, `muses/narrate/session.py`, `jwks.py`,
`wallet.py`, `entrypoint.py`, `router.py`) ne vérifie que via la clé PUBLIQUE
résolue par `iss` (cf. `muses/narrate/jwks.py`) et n'importe jamais ce
module. En déploiement réel, `MuseIssuer` (ou son équivalent) vit sur
l'instance émettrice, jamais dans la config du Hub.

Fournit :
- `generate_keypair` : paire RSA fraîche.
- `build_jwks_document` : document `{"keys": [...]}` publiable tel quel à
  `<iss>/.well-known/jwks.json` — consommable par
  `muses.narrate.jwks.JwksKeyResolver` (`RSAAlgorithm.from_jwk`).
- `mint_token` : signe un JWT court `{sub, iss, exp}` (forme attendue par
  `session.py:_claims_from_payload`).
- `MuseIssuer` : regroupe clé + `kid` + les deux opérations ci-dessus pour un
  usage direct depuis le CLI (`scripts/mint_muse_token.py`) et les tests.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

import jwt
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

DEFAULT_KEY_SIZE = 2048
DEFAULT_TTL_SECONDS = 3600


def generate_keypair(key_size: int = DEFAULT_KEY_SIZE) -> rsa.RSAPrivateKey:
    """Génère une paire de clés RSA fraîche.

    À exécuter côté instance émettrice uniquement — jamais dans le processus
    du Hub.
    """
    return rsa.generate_private_key(public_exponent=65537, key_size=key_size)


def private_key_pem(private_key: rsa.RSAPrivateKey) -> bytes:
    """Sérialise en PEM PKCS8 non chiffré (forme attendue par `jwt.encode`)."""
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def load_keypair_pem(pem_bytes: bytes) -> rsa.RSAPrivateKey:
    """Charge une clé privée RSA depuis un PEM PKCS8 non chiffré (`--key-file`)."""
    key = serialization.load_pem_private_key(pem_bytes, password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ValueError("le fichier de clé ne contient pas une clé privée RSA")
    return key


def fingerprint_kid(private_key: rsa.RSAPrivateKey) -> str:
    """`kid` déterministe dérivé de l'empreinte SHA-256 de la clé publique.

    Stable pour une même clé — utile avec `--key-file` : deux invocations du
    CLI sur le même fichier de clé produisent le même `kid`, donc un JWKS et
    un token mintés séparément restent cohérents entre eux.
    """
    public_der = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    digest = hashes.Hash(hashes.SHA256())
    digest.update(public_der)
    return digest.finalize().hex()[:16]


def build_jwks_document(private_key: rsa.RSAPrivateKey, *, kid: str) -> dict:
    """Construit le document JWKS `{"keys": [...]}` pour la clé publique.

    Réutilise `RSAAlgorithm.to_jwk` (PyJWT >=2.8, vendored ici en 2.11) pour
    l'encodage base64url de `n`/`e` plutôt que de le refaire à la main, puis
    normalise les champs (`kid`, `use`, `alg`) attendus par le parseur côté
    Hub (`muses/narrate/jwks.py:JwksKeyResolver._fetch_keys` exige `kid` +
    `kty == "RSA"`).
    """
    jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk.pop("key_ops", None)  # champ PyJWT non requis par notre parseur
    jwk["kid"] = kid
    jwk["use"] = "sig"
    jwk["alg"] = "RS256"
    return {"keys": [jwk]}


def mint_token(
    sub: str,
    iss: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    *,
    private_key: rsa.RSAPrivateKey,
    kid: str,
) -> str:
    """Signe un JWT court `{sub, iss, exp}` avec la clé privée de l'instance.

    Forme de claims alignée sur `session.py:_claims_from_payload` (`sub`,
    `iss`, `exp` requis par `JwtSessionVerifier`). `kid` est posé en en-tête
    pour permettre la résolution JWK côté Hub (`jwks.py`).
    """
    payload = {"sub": sub, "iss": iss, "exp": int(time.time()) + ttl_seconds}
    return jwt.encode(
        payload,
        private_key_pem(private_key),
        algorithm="RS256",
        headers={"kid": kid},
    )


@dataclass
class MuseIssuer:
    """Autorité d'émission d'une instance Muse : détient la clé privée.

    Regroupe keypair + `kid` + les opérations `jwks_document()` /
    `mint_token()` pour un usage direct depuis le CLI de référence et les
    tests de round-trip. Ne JAMAIS instancier côté Hub — c'est la
    matérialisation de "l'instance émettrice" (D18, D-89.1 : le Hub vérifie,
    il n'émet jamais).
    """

    private_key: rsa.RSAPrivateKey
    kid: str

    @classmethod
    def generate(
        cls,
        *,
        kid: str | None = None,
        key_size: int = DEFAULT_KEY_SIZE,
    ) -> "MuseIssuer":
        """Génère une nouvelle paire de clés et attribue un `kid` (auto si omis)."""
        private_key = generate_keypair(key_size)
        return cls(private_key=private_key, kid=kid or fingerprint_kid(private_key))

    @classmethod
    def from_pem(cls, pem_bytes: bytes, *, kid: str | None = None) -> "MuseIssuer":
        """Charge une clé privée existante (`--key-file`) plutôt que d'en générer une."""
        private_key = load_keypair_pem(pem_bytes)
        return cls(private_key=private_key, kid=kid or fingerprint_kid(private_key))

    def jwks_document(self) -> dict:
        """Document `{"keys": [...]}` à publier à `<iss>/.well-known/jwks.json`."""
        return build_jwks_document(self.private_key, kid=self.kid)

    def mint_token(
        self, sub: str, iss: str, ttl_seconds: int = DEFAULT_TTL_SECONDS
    ) -> str:
        """Signe un token de session pour `sub`/`iss` (wallet_key = `iss/sub`)."""
        return mint_token(
            sub, iss, ttl_seconds, private_key=self.private_key, kid=self.kid
        )

    def private_key_pem(self) -> bytes:
        """PEM PKCS8 non chiffré — persistance/reprise (ex. `--key-file` CLI)."""
        return private_key_pem(self.private_key)
