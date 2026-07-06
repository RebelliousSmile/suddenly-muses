"""H5 (#89, Phase 3) — durcissement du modèle de crédit en mode strict.

Couvre l'acceptance criteria de la Phase 3 :
- clé inconnue mais validement signée, `default_grant=0` -> 402
  `quota_exhausted`, rien débité, rien généré ;
- après `WalletStore.credit(wallet_key, k)` explicite, le même token réussit
  et débite exactement `n` (invariants de métrage H3 préservés) ;
- variante round-trip émetteur : `MuseIssuer` (Phase 2) + vérification JWKS
  (Phase 1) mintent/valident un token réellement asymétrique, sans secret
  partagé — scénario littéral de la section "Validation flow demonstration"
  du plan, condensé en test automatisé ;
- régression `off`/`stub` : le grant dev auto-appliqué reste inchangé.
"""

from __future__ import annotations

import time

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

from muses.api.server import create_app
from muses.narrate import (
    CannedNarrator,
    JwtSessionVerifier,
    MuseIssuer,
    StubSessionVerifier,
    WalletStore,
    make_jwks_key_lookup,
    make_session_dependency,
)

SECRET = "test-secret-0123456789-abcdefghij-LONG"  # >= 32 bytes (HMAC SHA256)
ISSUER = "muse.example"


def _hs256_token(*, sub: str = "unprovisioned", iss: str = ISSUER, ttl: int = 3600) -> str:
    return jwt.encode(
        {"sub": sub, "iss": iss, "exp": int(time.time()) + ttl}, SECRET, algorithm="HS256"
    )


def _request(n: int = 2) -> dict:
    return {
        "n": n,
        "packet": {
            "schema_version": 1,
            "cadre": {"lieu": "une taverne", "ambiance": None, "presents": []},
            "locuteur": {"nom": "Le Garde", "voix": "bourru"},
            "action_joueur": "Le joueur entre.",
            "hearing": "il entend une menace",
            "move": "barre la porte",
            "revealable": [],
            "withhold": [],
            "form": {"registre": "sec", "budget_revelation": 0, "ratio": "equilibre"},
        },
    }


class _CountingNarrator(CannedNarrator):
    """`CannedNarrator` qui compte ses appels pour vérifier "rien généré"."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def narrate(self, packet, n):  # type: ignore[override]
        self.calls += 1
        return super().narrate(packet, n)


def _strict_hs256_client(tmp_path, *, default_grant: int) -> tuple[TestClient, WalletStore, _CountingNarrator]:
    wallet = WalletStore(tmp_path / "w.sqlite", default_grant=default_grant)
    narrator = _CountingNarrator()
    app = create_app(
        tables=[],
        narrator=narrator,
        narrate_session_auth=make_session_dependency(JwtSessionVerifier(key=SECRET)),
        narrate_wallet=wallet,
    )
    return TestClient(app, raise_server_exceptions=False), wallet, narrator


def test_unknown_wallet_key_default_grant_zero_returns_402_nothing_debited(tmp_path) -> None:
    """Acceptance criteria Phase 3 #1 — clé inconnue + default_grant=0 -> 402."""
    client, wallet, narrator = _strict_hs256_client(tmp_path, default_grant=0)
    token = _hs256_token(sub="unprovisioned")

    resp = client.post(
        "/narrate", json=_request(n=2), headers={"Authorization": f"Bearer {token}"}
    )

    assert resp.status_code == 402
    assert resp.json()["error"] == "quota_exhausted"
    assert wallet.balance(f"{ISSUER}/unprovisioned") == 0
    assert narrator.calls == 0  # rien généré : le refus a lieu AVANT narrate()


def test_credit_then_same_token_succeeds_and_debits_exactly_n(tmp_path) -> None:
    """Acceptance criteria Phase 3 #2 — provisionnement explicite débloque l'accès."""
    client, wallet, narrator = _strict_hs256_client(tmp_path, default_grant=0)
    token = _hs256_token(sub="provisioned")
    wallet_key = f"{ISSUER}/provisioned"

    # Avant provisionnement : refusé (même garde que le test précédent).
    resp = client.post(
        "/narrate", json=_request(n=2), headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 402
    assert narrator.calls == 0

    # Provisionnement explicite (mécanisme requis par l'acceptance criteria,
    # ici appelé directement — l'endpoint admin HTTP est couvert séparément
    # dans tests/muses/api/test_admin.py).
    new_balance = wallet.credit(wallet_key, 5)
    assert new_balance == 5

    resp = client.post(
        "/narrate", json=_request(n=2), headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert len(resp.json()["candidates"]) == 2
    assert resp.headers.get("X-Muses-Credits-Spent") == "2"
    assert narrator.calls == 1
    # Débit APRÈS génération réussie, exactement n (invariant H3 préservé).
    assert wallet.balance(wallet_key) == 3


def test_insufficient_after_partial_credit_still_402_and_no_debit(tmp_path) -> None:
    """Un solde partiel (< n) reste refusé — pas de levier « n réduit »."""
    client, wallet, narrator = _strict_hs256_client(tmp_path, default_grant=0)
    token = _hs256_token(sub="partial")
    wallet_key = f"{ISSUER}/partial"
    wallet.credit(wallet_key, 1)

    resp = client.post(
        "/narrate", json=_request(n=2), headers={"Authorization": f"Bearer {token}"}
    )

    assert resp.status_code == 402
    assert resp.json()["error"] == "quota_exhausted"
    assert wallet.balance(wallet_key) == 1
    assert narrator.calls == 0


class _CountingJwksTransport:
    """Sert `.well-known/jwks.json` pour un `iss` donné (mirroring Phase 1 tests)."""

    def __init__(self, jwks_document: dict) -> None:
        self.calls = 0
        self._document = jwks_document

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        assert request.url.path == "/.well-known/jwks.json"
        return httpx.Response(200, json=self._document)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def test_issuer_round_trip_strict_jwks_rejects_then_accepts_after_credit(tmp_path) -> None:
    """Scénario littéral de "Validation flow demonstration" (section finale du
    plan) condensé en test : mint via `MuseIssuer` (Phase 2), vérification via
    JWKS résolu par `iss` (Phase 1), NO shared secret nulle part. En strict
    `default_grant=0`, la clé inconnue est refusée 402 jusqu'au provisionnement
    explicite, qui débloque exactement `n` candidats.
    """
    issuer = MuseIssuer.generate()
    transport = _CountingJwksTransport(issuer.jwks_document())

    lookup = make_jwks_key_lookup(issuers=[ISSUER], http_client=transport.client())
    verifier = JwtSessionVerifier(key_lookup=lookup, algorithms=["RS256"])

    wallet = WalletStore(tmp_path / "w.sqlite", default_grant=0)
    narrator = _CountingNarrator()
    app = create_app(
        tables=[],
        narrator=narrator,
        narrate_session_auth=make_session_dependency(verifier),
        narrate_wallet=wallet,
    )
    client = TestClient(app, raise_server_exceptions=False)

    token = issuer.mint_token("alice", ISSUER)
    wallet_key = f"{ISSUER}/alice"

    # 4. `POST /narrate` pour un utilisateur non provisionné -> 402.
    resp = client.post(
        "/narrate", json=_request(n=3), headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 402
    assert resp.json()["error"] == "quota_exhausted"
    assert wallet.balance(wallet_key) == 0
    assert narrator.calls == 0

    # 5. Provisionnement explicite puis rejeu -> 200, exactement n candidats.
    wallet.credit(wallet_key, 3)
    resp = client.post(
        "/narrate", json=_request(n=3), headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert len(resp.json()["candidates"]) == 3
    assert resp.headers.get("X-Muses-Credits-Spent") == "3"
    assert wallet.balance(wallet_key) == 0
    assert narrator.calls == 1


def test_off_stub_mode_dev_auto_grant_unchanged(tmp_path) -> None:
    """Acceptance criteria Phase 3 #3 — régression `stub` : le grant dev
    (`default_grant` explicite non nul) reste auto-appliqué sur clé inconnue,
    sans provisionnement, contrairement au mode strict."""
    wallet = WalletStore(tmp_path / "w.sqlite", default_grant=1000)
    narrator = _CountingNarrator()
    app = create_app(
        tables=[],
        narrator=narrator,
        narrate_session_auth=make_session_dependency(StubSessionVerifier()),
        narrate_wallet=wallet,
    )
    client = TestClient(app, raise_server_exceptions=False)

    # StubSessionVerifier ne vérifie pas la signature — un token non signé
    # (algorithme "none") suffit, cohérent avec le contrat dev/local.
    token = jwt.encode(
        {"sub": "dev-user", "iss": ISSUER, "exp": int(time.time()) + 3600},
        "unused",
        algorithm="HS256",
    )

    resp = client.post(
        "/narrate", json=_request(n=2), headers={"Authorization": f"Bearer {token}"}
    )

    assert resp.status_code == 200
    assert len(resp.json()["candidates"]) == 2
    assert narrator.calls == 1
    # Clé jamais créditée explicitement : le solde vient bien du grant dev.
    assert wallet.balance(f"{ISSUER}/dev-user") == 998
