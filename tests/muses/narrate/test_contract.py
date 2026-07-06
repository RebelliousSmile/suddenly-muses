"""H0 — Garde-couture du contrat `/narrate` (schéma réel de CN)."""

from __future__ import annotations

import pytest

from muses.narrate import schema as contract


def _valid_request() -> dict:
    return {
        "n": 3,
        "packet": {
            "schema_version": 1,
            "cadre": {
                "lieu": "une taverne enfumée",
                "ambiance": "crépusculaire",
                "presents": ["l'aubergiste"],
            },
            "locuteur": {"nom": "Le Garde", "voix": "bourru"},
            "action_joueur": "Le joueur demande ce qu'il y a dans la cave.",
            "hearing": "il entend une accusation voilée",
            "move": "se lève et barre le passage",
            "revealable": ["la cave sert d'entrepôt"],
            "withhold": ["qui a paye la rancon"],
            "form": {
                "registre": "tendu",
                "budget_revelation": 1,
                "ratio": "equilibre",
                "interdit_shape": ["monologue"],
            },
        },
    }


def test_declared_version_matches_expected() -> None:
    assert contract.declared_schema_version() == contract.EXPECTED_PACKET_SCHEMA_VERSION


def test_real_cn_schema_present() -> None:
    # Le vrai schéma de CN est déposé (plus de placeholder).
    assert not contract.schema_is_placeholder()


def test_valid_request_passes() -> None:
    contract.validate_request(_valid_request())  # ne lève pas


def test_unknown_top_level_field_rejected() -> None:
    body = _valid_request()
    body["evil"] = "injection"
    with pytest.raises(contract.PacketError):
        contract.validate_request(body)


def test_unknown_packet_field_rejected() -> None:
    body = _valid_request()
    body["packet"]["secret_canon"] = "ne devrait pas passer"
    with pytest.raises(contract.PacketError):
        contract.validate_request(body)


def test_wrong_schema_version_located_for_409() -> None:
    body = _valid_request()
    body["packet"]["schema_version"] = 2
    with pytest.raises(contract.PacketError) as exc:
        contract.validate_request(body)
    # La localisation permet au router de renvoyer 409 schema_incompatible.
    assert exc.value.location == contract.SCHEMA_VERSION_LOCATION


@pytest.mark.parametrize("n", [0, 6, 99])
def test_n_out_of_bounds_rejected(n: int) -> None:
    body = _valid_request()
    body["n"] = n
    with pytest.raises(contract.PacketError):
        contract.validate_request(body)


def test_missing_required_packet_field_rejected() -> None:
    body = _valid_request()
    del body["packet"]["move"]
    with pytest.raises(contract.PacketError):
        contract.validate_request(body)


def test_invalid_form_enum_rejected() -> None:
    body = _valid_request()
    body["packet"]["form"]["registre"] = "bogus"
    with pytest.raises(contract.PacketError):
        contract.validate_request(body)


def test_cadre_must_be_object() -> None:
    body = _valid_request()
    body["packet"]["cadre"] = "une taverne"  # string au lieu d'objet
    with pytest.raises(contract.PacketError):
        contract.validate_request(body)
