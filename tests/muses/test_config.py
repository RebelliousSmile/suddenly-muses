"""Tests config + entrypoint guard."""

import os

import pytest

from muses.config import ConfigError, load_config


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    """Réinitialise les vars Muses entre les tests."""
    for var in [
        "MUSES_TABLE_DIR", "MUSES_FEEDBACK_DIR", "MUSES_SNAPSHOT_DIR",
        "MUSES_ADMIN_TOKEN", "MUSES_SIGNATURE_MODE", "MUSES_SIGNATURE_MAX_AGE_SECONDS",
        "MUSES_ENCODER", "MUSES_ENCODER_MODEL", "MUSES_STUB_ENCODER_DIM",
        "MUSES_BIND_HOST", "MUSES_BIND_PORT", "MUSES_RATE_LIMIT_PER_MINUTE",
        "MUSES_LOG_LEVEL", "MUSES_LOG_FORMAT",
        "MUSES_NARRATE_AUTH_MODE", "MUSES_NARRATE_JWT_SECRET",
        "MUSES_NARRATE_JWT_ALGORITHM", "MUSES_NARRATE_JWT_ISSUERS",
        "MUSES_NARRATE_DEFAULT_GRANT", "MUSES_NARRATE_JWKS_ENABLED",
        "MUSES_NARRATE_JWKS_CACHE_TTL_SECONDS",
    ]:
        monkeypatch.delenv(var, raising=False)
    # Minimum requis : table_dir doit exister
    monkeypatch.setenv("MUSES_TABLE_DIR", str(tmp_path / "tables"))
    (tmp_path / "tables").mkdir()
    monkeypatch.setenv("MUSES_FEEDBACK_DIR", str(tmp_path / "feedback"))
    monkeypatch.setenv("MUSES_SNAPSHOT_DIR", str(tmp_path / "snaps"))
    return tmp_path


def test_default_local_bind_no_admin_token_ok(clean_env):
    """Bind 127.0.0.1 sans admin token = OK (dev local)."""
    settings = load_config()
    assert settings.bind_host == "127.0.0.1"
    assert settings.admin_token is None


def test_public_bind_without_admin_token_refused(clean_env, monkeypatch):
    monkeypatch.setenv("MUSES_BIND_HOST", "0.0.0.0")
    with pytest.raises(ConfigError, match="MUSES_ADMIN_TOKEN"):
        load_config()


def test_public_bind_with_admin_token_ok(clean_env, monkeypatch):
    monkeypatch.setenv("MUSES_BIND_HOST", "0.0.0.0")
    monkeypatch.setenv("MUSES_ADMIN_TOKEN", "secret")
    settings = load_config()
    assert settings.bind_host == "0.0.0.0"
    assert settings.admin_token == "secret"


def test_missing_table_dir_refused(clean_env, monkeypatch, tmp_path):
    monkeypatch.setenv("MUSES_TABLE_DIR", str(tmp_path / "absent"))
    with pytest.raises(ConfigError, match="n'existe pas"):
        load_config()


def test_invalid_signature_mode_refused(clean_env, monkeypatch):
    monkeypatch.setenv("MUSES_SIGNATURE_MODE", "weak")
    with pytest.raises(ConfigError, match="MUSES_SIGNATURE_MODE"):
        load_config()


def test_invalid_encoder_refused(clean_env, monkeypatch):
    monkeypatch.setenv("MUSES_ENCODER", "openai")
    with pytest.raises(ConfigError, match="MUSES_ENCODER"):
        load_config()


def test_invalid_int_refused(clean_env, monkeypatch):
    monkeypatch.setenv("MUSES_BIND_PORT", "not-a-number")
    with pytest.raises(ConfigError, match="entier"):
        load_config()


def test_strict_narrate_with_jwks_and_no_secret_does_not_raise(clean_env, monkeypatch):
    """H5 (#89) — la résolution JWK par iss (D18) est un substitut valide au secret."""
    monkeypatch.setenv("MUSES_NARRATE_AUTH_MODE", "strict")
    monkeypatch.setenv("MUSES_NARRATE_JWKS_ENABLED", "true")
    monkeypatch.setenv("MUSES_NARRATE_JWT_ISSUERS", "muse.example")
    monkeypatch.setenv("MUSES_ADMIN_TOKEN", "test-admin-token")
    settings = load_config()
    assert settings.narrate_jwks_enabled is True
    assert settings.narrate_jwt_secret is None


def test_strict_narrate_without_admin_token_refused(clean_env, monkeypatch):
    """Revue de code #89 (avertissement) — en strict, le portefeuille /narrate
    est toujours monté, donc POST /v1/admin/narrate/credit aussi. Sans
    MUSES_ADMIN_TOKEN, ce faucet de crédits serait ouvert à tout appelant,
    annulant le contrôle d'accès de default_grant=0."""
    monkeypatch.setenv("MUSES_NARRATE_AUTH_MODE", "strict")
    monkeypatch.setenv("MUSES_NARRATE_JWKS_ENABLED", "true")
    monkeypatch.setenv("MUSES_NARRATE_JWT_ISSUERS", "muse.example")
    with pytest.raises(ConfigError, match="MUSES_ADMIN_TOKEN"):
        load_config()


def test_strict_narrate_with_neither_jwks_nor_secret_refused(clean_env, monkeypatch):
    """Régression : ni secret ni JWKS en strict doit toujours échouer fermé."""
    monkeypatch.setenv("MUSES_NARRATE_AUTH_MODE", "strict")
    with pytest.raises(ConfigError, match="MUSES_NARRATE_JWT_SECRET"):
        load_config()


def test_strict_narrate_jwks_enabled_without_issuers_refused(clean_env, monkeypatch):
    """Sans allowlist d'issuers, la résolution JWK fetch n'importe quel domaine (SSRF)."""
    monkeypatch.setenv("MUSES_NARRATE_AUTH_MODE", "strict")
    monkeypatch.setenv("MUSES_NARRATE_JWKS_ENABLED", "true")
    with pytest.raises(ConfigError, match="MUSES_NARRATE_JWT_ISSUERS"):
        load_config()


def test_narrate_default_grant_defaults_to_zero_in_strict_mode(clean_env, monkeypatch):
    """H5 (#89, D-89.2) — strict sans MUSES_NARRATE_DEFAULT_GRANT explicite
    doit fermer la faille « n'importe quel token valide = crédits gratuits »."""
    monkeypatch.setenv("MUSES_NARRATE_AUTH_MODE", "strict")
    monkeypatch.setenv("MUSES_NARRATE_JWKS_ENABLED", "true")
    monkeypatch.setenv("MUSES_NARRATE_JWT_ISSUERS", "muse.example")
    monkeypatch.setenv("MUSES_ADMIN_TOKEN", "test-admin-token")
    settings = load_config()
    assert settings.narrate_default_grant == 0


def test_narrate_default_grant_defaults_to_1000_off_mode(clean_env):
    """Mode `off` (défaut) sans variable explicite : confort dev inchangé."""
    settings = load_config()
    assert settings.narrate_auth_mode == "off"
    assert settings.narrate_default_grant == 1000


def test_narrate_default_grant_defaults_to_1000_stub_mode(clean_env, monkeypatch):
    monkeypatch.setenv("MUSES_NARRATE_AUTH_MODE", "stub")
    settings = load_config()
    assert settings.narrate_default_grant == 1000


def test_narrate_default_grant_explicit_value_respected_in_strict_mode(clean_env, monkeypatch):
    """Une valeur explicitement posée est respectée telle quelle, même en
    strict — c'est alors un choix produit assumé (D-89.2), pas un accident."""
    monkeypatch.setenv("MUSES_NARRATE_AUTH_MODE", "strict")
    monkeypatch.setenv("MUSES_NARRATE_JWKS_ENABLED", "true")
    monkeypatch.setenv("MUSES_NARRATE_JWT_ISSUERS", "muse.example")
    monkeypatch.setenv("MUSES_NARRATE_DEFAULT_GRANT", "50")
    monkeypatch.setenv("MUSES_ADMIN_TOKEN", "test-admin-token")
    settings = load_config()
    assert settings.narrate_default_grant == 50


def test_narrate_default_grant_explicit_zero_respected_in_off_mode(clean_env, monkeypatch):
    """Une valeur explicite de 0 en mode `off` n'est pas silencieusement
    remontée à 1000 : seule l'ABSENCE de la variable dépend du mode."""
    monkeypatch.setenv("MUSES_NARRATE_DEFAULT_GRANT", "0")
    settings = load_config()
    assert settings.narrate_auth_mode == "off"
    assert settings.narrate_default_grant == 0


def test_narrate_default_grant_empty_value_treated_as_absent(clean_env, monkeypatch):
    """`MUSES_NARRATE_DEFAULT_GRANT=` (chaîne vide, ex. `.env` copié tel quel
    par un `docker-compose`/systemd `EnvironmentFile`) compte comme absente,
    pas comme "0 explicite" — cohérent avec le défaut dépendant du mode."""
    monkeypatch.setenv("MUSES_NARRATE_AUTH_MODE", "strict")
    monkeypatch.setenv("MUSES_NARRATE_JWKS_ENABLED", "true")
    monkeypatch.setenv("MUSES_NARRATE_JWT_ISSUERS", "muse.example")
    monkeypatch.setenv("MUSES_NARRATE_DEFAULT_GRANT", "")
    monkeypatch.setenv("MUSES_ADMIN_TOKEN", "test-admin-token")
    settings = load_config()
    assert settings.narrate_default_grant == 0


def test_narrate_invalid_default_grant_refused(clean_env, monkeypatch):
    monkeypatch.setenv("MUSES_NARRATE_DEFAULT_GRANT", "not-a-number")
    with pytest.raises(ConfigError, match="MUSES_NARRATE_DEFAULT_GRANT"):
        load_config()


def test_strict_narrate_nonzero_default_grant_logs_warning(clean_env, monkeypatch, caplog):
    """Non bloquant : strict + default_grant > 0 reste démarrable (choix produit
    valide, D-89.2) mais doit avertir fort — même intention que le garde
    `signature_mode=stub` déjà présent pour `bind_public`."""
    monkeypatch.setenv("MUSES_NARRATE_AUTH_MODE", "strict")
    monkeypatch.setenv("MUSES_NARRATE_JWKS_ENABLED", "true")
    monkeypatch.setenv("MUSES_NARRATE_JWT_ISSUERS", "muse.example")
    monkeypatch.setenv("MUSES_NARRATE_DEFAULT_GRANT", "10")
    monkeypatch.setenv("MUSES_ADMIN_TOKEN", "test-admin-token")
    with caplog.at_level("WARNING", logger="muses.config"):
        settings = load_config()
    assert settings.narrate_default_grant == 10
    assert any(
        "strict" in r.getMessage().lower()
        for r in caplog.records
        if r.name == "muses.config"
    )


def test_table_jsonl_paths_lists_only_jsonl(clean_env, tmp_path):
    table_dir = tmp_path / "tables"
    (table_dir / "fragments.jsonl").write_text("")
    (table_dir / "beats.jsonl").write_text("")
    (table_dir / "ignored.txt").write_text("")
    (table_dir / "fragments.sqlite").write_text("")
    settings = load_config()
    names = sorted(p.name for p in settings.table_jsonl_paths)
    assert names == ["beats.jsonl", "fragments.jsonl"]
