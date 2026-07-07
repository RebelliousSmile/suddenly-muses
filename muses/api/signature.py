"""Vérification cryptographique des signatures HTTP ActivityPub draft-cavage.

Mode strict (production) — implémente :
1. Parsing du header `Signature`.
2. **Imposition** d'un jeu minimal d'en-têtes couverts par la signature
   (`(request-target)`, `host`, `date` ; + `digest` si la requête a un corps) —
   sinon rejeu / body-swap possibles (HUB-F1 #90).
3. Anti-replay : rejet si `Date` plus ancien que `max_age_seconds`.
4. **Vérification du `Digest`** du corps (intégrité) pour toute requête à corps.
5. Reconstruction du signing string canonique depuis les headers listés.
6. Résolution de l'acteur (`GET keyId`) avec **garde SSRF** (https + IP publique,
   pas de redirection).
7. Vérification RSA-SHA256 contre `publicKey.publicKeyPem` de l'acteur.

La résolution de l'acteur est cachée en mémoire (TTL paramétrable). Pour les
tests, on injecte un `KeyResolver` qui renvoie directement les clés sans réseau.

Référence : draft-cavage-http-signatures-12 (encore utilisé par ActivityPub).
Invariants à garder alignés avec `suddenly/activitypub/signatures.py` (repo Sud).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import logging
import socket
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable, Protocol

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import HTTPException, Request, status

from muses.api.auth import ParsedSignature, parse_http_signature


logger = logging.getLogger("muses.signature")

# En-têtes qui DOIVENT être couverts par la signature. `digest` s'y ajoute
# dès que la requête porte un corps.
_REQUIRED_SIGNED_HEADERS = ("(request-target)", "host", "date")


class SignatureInvalid(HTTPException):
    """Signature rejetée — toujours 401 vers le caller."""

    def __init__(self, detail: str):
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


class KeyResolver(Protocol):
    """Récupère la clé publique PEM pour un `keyId` donné."""

    def resolve(self, key_id: str) -> str:
        ...


def _assert_public_actor_url(url: str) -> None:
    """Garde SSRF : n'autorise que du `https` résolvant vers une IP routable.

    Refuse loopback / privées / link-local (169.254.169.254) / réservées. Note :
    la résolution DNS ici puis le fetch httpx laissent une fenêtre TOCTOU
    résiduelle ; les redirections sont désactivées côté fetch pour la réduire.
    """
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https":
        raise SignatureInvalid(f"keyId doit être https, reçu {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise SignatureInvalid("keyId sans hôte")
    try:
        infos = socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise SignatureInvalid(f"Résolution DNS impossible pour {host!r}: {exc}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise SignatureInvalid(
                f"keyId {host!r} résout vers une IP non routable ({ip}) — SSRF bloqué"
            )


class HttpKeyResolver:
    """Résolveur par défaut : fetch l'acteur ActivityPub par HTTP avec cache TTL.

    L'URL du keyId désigne typiquement `https://instance/users/x#main-key`.
    On fetch `https://instance/users/x` (le `#fragment` est ignoré côté HTTP)
    avec `Accept: application/activity+json` et on lit `publicKey.publicKeyPem`.
    Garde SSRF appliquée avant tout fetch ; redirections désactivées.
    """

    def __init__(
        self,
        *,
        ttl_seconds: int = 3600,
        timeout_seconds: float = 5.0,
        http_client: httpx.Client | None = None,
    ):
        self.ttl_seconds = ttl_seconds
        self._cache: dict[str, tuple[float, str]] = {}
        self._client = http_client or httpx.Client(timeout=timeout_seconds)

    def resolve(self, key_id: str) -> str:
        now = time.monotonic()
        cached = self._cache.get(key_id)
        if cached and (now - cached[0]) < self.ttl_seconds:
            return cached[1]

        actor_url = key_id.split("#", 1)[0]
        _assert_public_actor_url(actor_url)  # garde SSRF avant tout réseau
        try:
            resp = self._client.get(
                actor_url,
                headers={"Accept": "application/activity+json"},
                follow_redirects=False,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise SignatureInvalid(
                f"Impossible de résoudre l'acteur {actor_url!r}: {exc}"
            ) from exc

        data = resp.json()
        pubkey = data.get("publicKey") or {}
        pem = pubkey.get("publicKeyPem")
        if not pem:
            raise SignatureInvalid(
                f"L'acteur {actor_url!r} n'expose pas publicKey.publicKeyPem"
            )
        self._cache[key_id] = (now, pem)
        return pem


@dataclass
class _SignatureMeta:
    """Métadonnées extraites du header Signature."""

    key_id: str
    algorithm: str
    headers: list[str]   # liste des headers couverts par la signature
    signature_b64: str


def _parse_meta(raw: str) -> _SignatureMeta | None:
    import re

    parts = dict(re.findall(r'(\w+)="([^"]*)"', raw or ""))
    if "keyId" not in parts or "signature" not in parts:
        return None
    headers_str = parts.get("headers", "(request-target) host date")
    return _SignatureMeta(
        key_id=parts["keyId"],
        algorithm=parts.get("algorithm", "rsa-sha256"),
        headers=headers_str.split(),
        signature_b64=parts["signature"],
    )


def _enforce_signed_headers(meta_headers: list[str], *, has_body: bool) -> None:
    """Rejette si la signature ne couvre pas les en-têtes obligatoires.

    Sans `date` signé → rejeu possible ; sans `digest` signé (corps présent) →
    body-swap possible.
    """
    covered = {h.lower() for h in meta_headers}
    required = set(_REQUIRED_SIGNED_HEADERS)
    if has_body:
        required.add("digest")
    missing = required - covered
    if missing:
        raise SignatureInvalid(
            "En-têtes obligatoires non couverts par la signature : "
            + ", ".join(sorted(missing))
        )


def _verify_digest(request: Request, body: bytes) -> None:
    """Vérifie le header `Digest` (SHA-256) contre le corps réel."""
    header = request.headers.get("digest")
    if not header:
        raise SignatureInvalid("Header Digest requis pour une requête à corps")
    expected = base64.b64encode(hashlib.sha256(body).digest()).decode()
    for part in header.split(","):
        name, _sep, value = part.strip().partition("=")
        if name.strip().lower() in ("sha-256", "sha256"):
            if hmac.compare_digest(value.strip(), expected):
                return
            raise SignatureInvalid("Digest SHA-256 ne correspond pas au corps (intégrité)")
    raise SignatureInvalid("Digest SHA-256 absent du header Digest")


def _build_signing_string(request: Request, headers: list[str]) -> str:
    """Reconstruit la chaîne canonique signée.

    Format : chaque ligne `"<header>: <value>"`, séparées par `\\n`. Pour
    `(request-target)` : `"(request-target): <method-lower> <path-with-query>"`.
    """
    lines: list[str] = []
    for h in headers:
        h_low = h.lower()
        if h_low == "(request-target)":
            target = request.url.path
            if request.url.query:
                target = f"{target}?{request.url.query}"
            lines.append(f"(request-target): {request.method.lower()} {target}")
        else:
            value = request.headers.get(h_low)
            if value is None:
                raise SignatureInvalid(
                    f"Header {h!r} listé dans la signature mais absent de la requête"
                )
            lines.append(f"{h_low}: {value}")
    return "\n".join(lines)


def _verify_date_freshness(request: Request, max_age_seconds: int) -> None:
    date_header = request.headers.get("date")
    if not date_header:
        raise SignatureInvalid("Header Date requis en mode strict")
    try:
        request_time = parsedate_to_datetime(date_header)
    except (TypeError, ValueError) as exc:
        raise SignatureInvalid(f"Header Date non parsable: {date_header!r}") from exc

    if request_time.tzinfo is None:
        request_time = request_time.replace(tzinfo=timezone.utc)
    age = (datetime.now(tz=timezone.utc) - request_time).total_seconds()
    if age > max_age_seconds:
        raise SignatureInvalid(
            f"Requête trop ancienne ({int(age)}s > {max_age_seconds}s, anti-replay)"
        )
    if age < -max_age_seconds:
        raise SignatureInvalid(
            f"Requête datée dans le futur ({int(age)}s, horloge désynchronisée)"
        )


def _verify_signature(public_key_pem: str, signing_string: str, signature_b64: str) -> None:
    try:
        public_key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
    except Exception as exc:
        raise SignatureInvalid(f"Clé publique non chargeable: {exc}") from exc

    if not isinstance(public_key, rsa.RSAPublicKey):
        raise SignatureInvalid("La clé publique n'est pas RSA — algorithme non supporté")

    try:
        signature = base64.b64decode(signature_b64)
    except Exception as exc:
        raise SignatureInvalid("Signature non décodable en base64") from exc

    try:
        public_key.verify(
            signature,
            signing_string.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except InvalidSignature as exc:
        raise SignatureInvalid("Signature RSA-SHA256 invalide") from exc


def verify_signature_strict(
    request: Request,
    *,
    key_resolver: KeyResolver,
    max_age_seconds: int = 300,
    body: bytes = b"",
) -> ParsedSignature:
    """Vérifie cryptographiquement la signature d'une requête entrante.

    `body` = corps brut (pour la vérification du `Digest`). Renvoie le
    `ParsedSignature` en cas de succès, lève `SignatureInvalid` (401) sinon.
    """
    raw = request.headers.get("signature")
    if not raw:
        raise SignatureInvalid("Header Signature absent")

    meta = _parse_meta(raw)
    if meta is None:
        raise SignatureInvalid("Header Signature non parsable")

    if meta.algorithm.lower() not in ("rsa-sha256", "hs2019"):
        raise SignatureInvalid(
            f"Algorithme {meta.algorithm!r} non supporté (attendu rsa-sha256)"
        )

    has_body = bool(body)
    _enforce_signed_headers(meta.headers, has_body=has_body)
    _verify_date_freshness(request, max_age_seconds)
    if has_body:
        _verify_digest(request, body)

    signing_string = _build_signing_string(request, meta.headers)
    public_key_pem = key_resolver.resolve(meta.key_id)
    _verify_signature(public_key_pem, signing_string, meta.signature_b64)

    logger.info("signature OK pour keyId=%s headers=%s", meta.key_id, meta.headers)
    return ParsedSignature(
        key_id=meta.key_id,
        algorithm=meta.algorithm,
        signature_b64=meta.signature_b64,
        raw=raw,
    )


def make_strict_dependency(
    key_resolver: KeyResolver,
    *,
    max_age_seconds: int = 300,
) -> Callable[[Request], ParsedSignature]:
    """Construit une dependency FastAPI qui vérifie strictement la signature.

    Async pour lire le corps (`await request.body()`) — nécessaire à la
    vérification du `Digest`. Le corps est mis en cache par Starlette, donc le
    modèle Pydantic de l'endpoint le relit sans surcoût.
    """

    async def _dep(request: Request) -> ParsedSignature:
        body = await request.body()
        return verify_signature_strict(
            request,
            key_resolver=key_resolver,
            max_age_seconds=max_age_seconds,
            body=body,
        )

    return _dep
