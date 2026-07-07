"""Hub-B — Garde-fou du reçu de provenance du contrat `/narrate`.

Le reçu (`contract/PROVENANCE.json`) rend la synchronisation CN → Hub
vérifiable : il porte le commit CN source et le hash du schéma importé. Ces
tests prouvent que le reçu existe, est bien formé, et ne peut pas dériver du
`schema.json` réellement déposé.
"""

from __future__ import annotations

import re

import pytest

from muses.narrate import schema as contract

_REQUIRED_FIELDS = {
    "receipt_version",
    "artifact",
    "source_repo",
    "source_path",
    "source_commit",
    "source_commit_date",
    "imported_at",
    "schema_sha256",
    "backfill_required",
}

_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def test_receipt_parses() -> None:
    assert isinstance(contract.load_provenance(), dict)


def test_required_fields_present() -> None:
    missing = _REQUIRED_FIELDS - set(contract.load_provenance())
    assert not missing, f"champs manquants dans le reçu : {missing}"


def test_recorded_hash_matches_schema() -> None:
    # LE test central : le reçu décrit bien le schema.json présent sur le disque.
    # Toute édition manuelle de schema.json hors du script d'import casse ici.
    receipt = contract.load_provenance()
    assert _SHA256_RE.match(receipt["schema_sha256"]), "schema_sha256 mal formé"
    assert contract.provenance_matches_schema(), (
        "PROVENANCE.json ne correspond plus à schema.json — réimporter via "
        "scripts/import_narrate_contract.sh"
    )


def test_backfill_flag_is_bool() -> None:
    assert isinstance(contract.load_provenance()["backfill_required"], bool)


def test_source_commit_is_real_sha_once_backfilled() -> None:
    """Une fois l'import scripté passé, `source_commit` DOIT être un SHA git réel.

    Tant que `backfill_required` est vrai (schéma hérité de PR #83), le SHA CN
    n'est pas encore connu — on tolère `unknown`. Dès qu'il passe à faux, le reçu
    doit résoudre vers un commit réel (Done #1 de Hub-B).
    """
    receipt = contract.load_provenance()
    if receipt["backfill_required"]:
        pytest.skip("schéma hérité (PR #83) : SHA CN à backfiller au prochain import")
    assert _SHA1_RE.match(receipt["source_commit"]), (
        f"source_commit doit être un SHA git 40-hex, pas {receipt['source_commit']!r}"
    )
    assert receipt["source_commit_date"] != "unknown"
