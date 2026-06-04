"""H0 — Garde-couture du contrat `/narrate`.

Deux gardes :
- `test_declared_version_matches_expected` : le schéma porte bien la version
  attendue (1). Devient ROUGE si `packet.rs` évolue sans répercussion ici.
- `test_real_cn_schema_present` : tripwire `xfail(strict)` tant que le schéma
  est un placeholder. Quand le vrai `schema.json` de CN est déposé, ce test
  xpass → l'échec strict force à retirer le marqueur xfail (nettoyage H0).
"""

from __future__ import annotations

import pytest

from muses.narrate import schema as contract


def _valid_request() -> dict:
    return {
        "schema_version": 1,
        "n": 3,
        "packet": {
            "cadre": "Une taverne enfumée au crépuscule.",
            "locuteur": {"nom": "Le Garde", "voix": "bourru"},
            "action_joueur": "Le joueur demande ce qu'il y a dans la cave.",
            "hearing": ["le craquement du feu"],
            "mouvement": "s'approche du comptoir",
            "revealable": ["la cave sert d'entrepôt"],
            "withhold": ["le passage secret vers les egouts"],
            "form": {
                "registre": "familier",
                "budget": 60,
                "ratio": 0.5,
                "shapes_interdites": ["liste"],
            },
        },
    }


def test_declared_version_matches_expected() -> None:
    assert contract.declared_schema_version() == contract.EXPECTED_PACKET_SCHEMA_VERSION


@pytest.mark.xfail(
    strict=True,
    reason="H0 : placeholder en place. Déposer le schema.json généré par CN "
    "(retirer x-suddenly-placeholder) fera xpass → retirer ce xfail.",
)
def test_real_cn_schema_present() -> None:
    assert not contract.schema_is_placeholder()


def test_valid_request_passes() -> None:
    contract.validate_request(_valid_request())  # ne lève pas


def test_unknown_top_level_field_rejected() -> None:
    body = _valid_request()
    body["evil"] = "injection"
    with pytest.raises(contract.PacketError):
        contract.validate_request(body)


def test_unknown_nested_field_rejected() -> None:
    body = _valid_request()
    body["packet"]["secret_canon"] = "ne devrait pas passer"
    with pytest.raises(contract.PacketError):
        contract.validate_request(body)


def test_wrong_schema_version_rejected() -> None:
    body = _valid_request()
    body["schema_version"] = 2
    with pytest.raises(contract.PacketError):
        contract.validate_request(body)


@pytest.mark.parametrize("n", [0, 6, 99])
def test_n_out_of_bounds_rejected(n: int) -> None:
    body = _valid_request()
    body["n"] = n
    with pytest.raises(contract.PacketError):
        contract.validate_request(body)


def test_missing_required_field_rejected() -> None:
    body = _valid_request()
    del body["packet"]["cadre"]
    with pytest.raises(contract.PacketError):
        contract.validate_request(body)
