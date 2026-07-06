"""H3 — portefeuille Muse."""

from __future__ import annotations

from muses.narrate.wallet import WalletStore


def test_unknown_key_returns_default_grant(tmp_path) -> None:
    w = WalletStore(tmp_path / "w.sqlite", default_grant=500)
    assert w.balance("muse/u1") == 500


def test_debit_reduces_balance(tmp_path) -> None:
    w = WalletStore(tmp_path / "w.sqlite", default_grant=10)
    assert w.debit("muse/u1", 3) == 7
    assert w.balance("muse/u1") == 7


def test_debit_floors_at_zero(tmp_path) -> None:
    w = WalletStore(tmp_path / "w.sqlite", default_grant=2)
    assert w.debit("muse/u1", 5) == 0
    assert w.balance("muse/u1") == 0


def test_credit_adds(tmp_path) -> None:
    w = WalletStore(tmp_path / "w.sqlite", default_grant=0)
    assert w.credit("muse/u1", 4) == 4
    assert w.debit("muse/u1", 1) == 3


def test_persistence_across_instances(tmp_path) -> None:
    path = tmp_path / "w.sqlite"
    WalletStore(path, default_grant=10).debit("muse/u1", 4)
    assert WalletStore(path, default_grant=10).balance("muse/u1") == 6
