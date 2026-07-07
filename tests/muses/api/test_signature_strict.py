"""Vérification cryptographique des signatures HTTP + durcissements HUB-F1 (#90)."""

import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from muses.api.signature import (
    KeyResolver,
    SignatureInvalid,
    _assert_public_actor_url,
    _enforce_signed_headers,
    make_strict_dependency,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _generate_keypair() -> tuple[rsa.RSAPrivateKey, str]:
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return priv, pub_pem


def _digest(body: bytes) -> str:
    return "SHA-256=" + base64.b64encode(hashlib.sha256(body).digest()).decode()


def _signing_string(method: str, path: str, headers: dict[str, str], covered: list[str]) -> str:
    lines = []
    for h in covered:
        if h == "(request-target)":
            lines.append(f"(request-target): {method.lower()} {path}")
        else:
            lines.append(f"{h}: {headers[h]}")
    return "\n".join(lines)


def _sign(priv: rsa.RSAPrivateKey, signing_string: str) -> str:
    sig = priv.sign(signing_string.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(sig).decode()


def _sig_header(*, key_id: str, covered: list[str], signature_b64: str, algorithm: str = "rsa-sha256") -> str:
    return (
        f'keyId="{key_id}",algorithm="{algorithm}",'
        f'headers="{" ".join(covered)}",signature="{signature_b64}"'
    )


class _StaticResolver:
    def __init__(self, mapping: dict[str, str]):
        self._mapping = mapping

    def resolve(self, key_id: str) -> str:
        if key_id not in self._mapping:
            raise SignatureInvalid(f"keyId inconnu: {key_id}")
        return self._mapping[key_id]


def _make_app(resolver: KeyResolver, max_age_seconds: int = 300) -> FastAPI:
    app = FastAPI()
    dep = make_strict_dependency(resolver, max_age_seconds=max_age_seconds)

    @app.post("/protected")
    def protected(sig=Depends(dep)) -> dict:
        return {"key_id": sig.key_id}

    return app


def _signed_post(
    client: TestClient,
    priv: rsa.RSAPrivateKey,
    key_id: str,
    *,
    body_obj: dict | None = None,
    covered: list[str] | None = None,
    with_digest: bool = True,
    date: str | None = None,
    sent_body: bytes | None = None,
    algorithm: str = "rsa-sha256",
):
    body = b"" if body_obj is None else json.dumps(body_obj).encode()
    if date is None:
        date = format_datetime(datetime.now(tz=timezone.utc), usegmt=True)
    headers = {"host": "testserver", "date": date}
    if with_digest and body:
        headers["digest"] = _digest(body)
    if covered is None:
        covered = ["(request-target)", "host", "date"]
        if with_digest and body:
            covered.append("digest")
    sig = _sign(priv, _signing_string("POST", "/protected", headers, covered))
    send = {**headers, "Signature": _sig_header(key_id=key_id, covered=covered, signature_b64=sig, algorithm=algorithm)}
    return client.post(
        "/protected",
        content=body if sent_body is None else sent_body,
        headers={**send, "Content-Type": "application/json"},
    )


# --------------------------------------------------------------------------- #
# Chemin nominal
# --------------------------------------------------------------------------- #


def test_valid_signature_accepted():
    priv, pub = _generate_keypair()
    key_id = "https://exemple.tld/users/alice#main-key"
    client = TestClient(_make_app(_StaticResolver({key_id: pub})))
    resp = _signed_post(client, priv, key_id, body_obj={"x": 1})
    assert resp.status_code == 200, resp.text
    assert resp.json()["key_id"] == key_id


# --------------------------------------------------------------------------- #
# HUB-F1.1 — Digest / intégrité du corps
# --------------------------------------------------------------------------- #


def test_tampered_body_now_rejected():
    """Ce qui passait avant (body-swap) est maintenant bloqué par le Digest."""
    priv, pub = _generate_keypair()
    key_id = "https://exemple.tld/key"
    client = TestClient(_make_app(_StaticResolver({key_id: pub})))
    # Digest calculé sur {"x":1} mais corps réellement envoyé = autre chose.
    resp = _signed_post(client, priv, key_id, body_obj={"x": 1}, sent_body=b'{"tampered":true}')
    assert resp.status_code == 401
    assert "digest" in resp.json()["detail"].lower()


def test_missing_digest_header_rejected():
    priv, pub = _generate_keypair()
    key_id = "https://exemple.tld/key"
    client = TestClient(_make_app(_StaticResolver({key_id: pub})))
    resp = _signed_post(client, priv, key_id, body_obj={"x": 1}, with_digest=False)
    assert resp.status_code == 401
    assert "digest" in resp.json()["detail"].lower()


# --------------------------------------------------------------------------- #
# HUB-F1.2 — En-têtes signés imposés
# --------------------------------------------------------------------------- #


def test_date_not_covered_rejected():
    # date absente des headers signés → rejeu possible → refus.
    priv, pub = _generate_keypair()
    key_id = "https://exemple.tld/key"
    client = TestClient(_make_app(_StaticResolver({key_id: pub})))
    resp = _signed_post(
        client, priv, key_id, body_obj={"x": 1},
        covered=["(request-target)", "host", "digest"],
    )
    assert resp.status_code == 401
    assert "date" in resp.json()["detail"].lower()


def test_enforce_signed_headers_unit():
    _enforce_signed_headers(["(request-target)", "host", "date"], has_body=False)  # ok
    with pytest.raises(SignatureInvalid):
        _enforce_signed_headers(["(request-target)", "host", "date"], has_body=True)  # digest manquant
    with pytest.raises(SignatureInvalid):
        _enforce_signed_headers(["(request-target)", "host"], has_body=False)  # date manquante


# --------------------------------------------------------------------------- #
# HUB-F1.3 — Garde SSRF sur le fetch de clé
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/users/x",       # loopback
        "https://10.0.0.1/users/x",        # RFC1918
        "https://169.254.169.254/latest",  # link-local (metadata)
        "http://93.184.216.34/users/x",    # non-https
    ],
)
def test_ssrf_guard_rejects_unsafe(url: str):
    with pytest.raises(SignatureInvalid):
        _assert_public_actor_url(url)


def test_ssrf_guard_accepts_public_ip():
    _assert_public_actor_url("https://93.184.216.34/users/x")  # ne lève pas


# --------------------------------------------------------------------------- #
# Signature / algorithme / replay / keyId
# --------------------------------------------------------------------------- #


def test_wrong_signature_rejected():
    priv_attacker, _ = _generate_keypair()
    _, pub_legit = _generate_keypair()
    key_id = "https://exemple.tld/key"
    client = TestClient(_make_app(_StaticResolver({key_id: pub_legit})))
    resp = _signed_post(client, priv_attacker, key_id, body_obj={"x": 1})
    assert resp.status_code == 401
    assert "invalide" in resp.json()["detail"].lower()


def test_replay_old_request_rejected():
    priv, pub = _generate_keypair()
    key_id = "https://exemple.tld/key"
    old = format_datetime(datetime.now(tz=timezone.utc) - timedelta(hours=1), usegmt=True)
    client = TestClient(_make_app(_StaticResolver({key_id: pub})))
    resp = _signed_post(client, priv, key_id, body_obj={"x": 1}, date=old)
    assert resp.status_code == 401
    assert "anti-replay" in resp.json()["detail"].lower()


def test_missing_signature_rejected():
    priv, pub = _generate_keypair()
    client = TestClient(_make_app(_StaticResolver({"x": pub})))
    resp = client.post("/protected", json={})
    assert resp.status_code == 401


def test_unknown_keyid_rejected():
    priv, pub = _generate_keypair()
    client = TestClient(_make_app(_StaticResolver({"https://other.tld/key": pub})))
    resp = _signed_post(client, priv, "https://unknown.tld/key", body_obj={"x": 1})
    assert resp.status_code == 401
    assert "inconnu" in resp.json()["detail"].lower()


def test_unsupported_algorithm_rejected():
    priv, pub = _generate_keypair()
    key_id = "https://exemple.tld/key"
    client = TestClient(_make_app(_StaticResolver({key_id: pub})))
    resp = _signed_post(client, priv, key_id, body_obj={"x": 1}, algorithm="ed25519")
    assert resp.status_code == 401
    assert "ed25519" in resp.json()["detail"]
