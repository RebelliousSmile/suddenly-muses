"""Tests T35 — endpoint /v1/admin/coverage + module compute_coverage.

H5 (#89, Phase 3) — endpoint optionnel /v1/admin/narrate/credit, réutilisant
le garde d'auth déjà couvert ci-dessous pour /coverage.
"""

from fastapi.testclient import TestClient

from muses.api.admin import compute_coverage
from muses.api.server import create_app
from muses.ingestion.pipeline import TablePaths, ingest
from muses.narrate import CannedNarrator, WalletStore
from muses.tables.embeddings import StubEncoder


def _ingest(table_dir, tags, n=2):
    paths = TablePaths.from_dir(table_dir)
    encoder = StubEncoder(dim=8)
    for i in range(n):
        ingest({
            "level": "fragment",
            "tags": tags,
            "content": {"text": f"text {i}", "char_pov": "neutral"},
            "source": "bootstrap",
        }, paths, encoder=encoder, verify_signature=False)
    return paths.jsonl


def test_compute_coverage_aggregates(tmp_path):
    table = _ingest(tmp_path / "tbl", {
        "univers": ["medieval_fantastique"], "situation": ["combat"],
    }, n=3)
    cells = compute_coverage([table])
    assert len(cells) == 1
    cell = cells[0]
    assert cell.counts_by_level["fragment"] == 3
    assert cell.last_contribution is not None


def test_compute_coverage_multiple_cells(tmp_path):
    t1 = _ingest(tmp_path / "med", {"univers": ["medieval_fantastique"]})
    t2 = _ingest(tmp_path / "cyber", {"univers": ["cyberpunk"]})
    cells = compute_coverage([t1, t2])
    assert len(cells) == 2


def test_admin_endpoint_no_token_when_admin_disabled(tmp_path):
    table = _ingest(tmp_path / "tbl", {"univers": ["medieval_fantastique"]})
    app = create_app(tables=[table], admin_token=None)
    client = TestClient(app)
    resp = client.get("/v1/admin/coverage")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_cells"] == 1


def test_admin_endpoint_requires_token_when_set(tmp_path):
    table = _ingest(tmp_path / "tbl", {"univers": ["medieval_fantastique"]})
    app = create_app(tables=[table], admin_token="s3cret")
    client = TestClient(app)
    resp = client.get("/v1/admin/coverage")
    assert resp.status_code == 403
    resp = client.get("/v1/admin/coverage", headers={"X-Admin-Token": "wrong"})
    assert resp.status_code == 403
    resp = client.get("/v1/admin/coverage", headers={"X-Admin-Token": "s3cret"})
    assert resp.status_code == 200


def test_narrate_credit_endpoint_not_mounted_without_wallet(tmp_path):
    """Sans `narrate_wallet` configuré, la route n'existe pas (404, pas 403)."""
    app = create_app(tables=[], admin_token="s3cret")
    client = TestClient(app)
    resp = client.post(
        "/v1/admin/narrate/credit",
        json={"wallet_key": "muse.example/u1", "amount": 5},
        headers={"X-Admin-Token": "s3cret"},
    )
    assert resp.status_code == 404


def test_narrate_credit_endpoint_requires_token_when_set(tmp_path):
    wallet = WalletStore(tmp_path / "w.sqlite", default_grant=0)
    app = create_app(
        tables=[], narrator=CannedNarrator(), narrate_wallet=wallet, admin_token="s3cret",
    )
    client = TestClient(app)
    body = {"wallet_key": "muse.example/u1", "amount": 5}

    resp = client.post("/v1/admin/narrate/credit", json=body)
    assert resp.status_code == 403

    resp = client.post(
        "/v1/admin/narrate/credit", json=body, headers={"X-Admin-Token": "wrong"}
    )
    assert resp.status_code == 403

    resp = client.post(
        "/v1/admin/narrate/credit", json=body, headers={"X-Admin-Token": "s3cret"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"wallet_key": "muse.example/u1", "balance": 5}
    assert wallet.balance("muse.example/u1") == 5


def test_narrate_credit_endpoint_open_when_admin_disabled(tmp_path):
    """Cohérent avec /coverage : admin_token=None -> pas d'auth (dev/tests)."""
    wallet = WalletStore(tmp_path / "w.sqlite", default_grant=0)
    app = create_app(
        tables=[], narrator=CannedNarrator(), narrate_wallet=wallet, admin_token=None,
    )
    client = TestClient(app)

    resp = client.post(
        "/v1/admin/narrate/credit",
        json={"wallet_key": "muse.example/u1", "amount": 7},
    )
    assert resp.status_code == 200
    assert resp.json() == {"wallet_key": "muse.example/u1", "balance": 7}


def test_narrate_credit_endpoint_rejects_negative_amount(tmp_path):
    wallet = WalletStore(tmp_path / "w.sqlite", default_grant=0)
    app = create_app(
        tables=[], narrator=CannedNarrator(), narrate_wallet=wallet, admin_token=None,
    )
    client = TestClient(app)

    resp = client.post(
        "/v1/admin/narrate/credit",
        json={"wallet_key": "muse.example/u1", "amount": -1},
    )
    assert resp.status_code == 400
    assert wallet.balance("muse.example/u1") == 0
