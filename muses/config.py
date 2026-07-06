"""Configuration runtime du service Muses à partir des variables d'environnement.

Voir `.env.example` pour la liste complète. La fonction `load_config()` est
appelée au démarrage par `muses.api.entrypoint` et expose une `Settings` typée
qui guide le câblage de `create_app()`.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


SignatureMode = Literal["stub", "strict"]
EncoderKind = Literal["stub", "sentence_transformer"]
LogFormat = Literal["text", "json"]
NarrateAuthMode = Literal["off", "stub", "strict"]


@dataclass
class Settings:
    """Configuration runtime résolue depuis l'environnement."""

    table_dir: Path
    feedback_dir: Path
    snapshot_dir: Path

    admin_token: str | None
    signature_mode: SignatureMode
    signature_max_age_seconds: int

    encoder: EncoderKind
    encoder_model: str
    stub_encoder_dim: int

    bind_host: str
    bind_port: int
    rate_limit_per_minute: int

    log_level: str
    log_format: LogFormat

    # Relais /narrate (H3) — auth session + métrage. `off` = ouvert, pas de débit.
    narrate_auth_mode: NarrateAuthMode
    narrate_jwt_secret: str | None
    narrate_jwt_algorithm: str
    narrate_jwt_issuers: list[str] | None
    narrate_default_grant: int
    narrate_cors_origins: list[str] | None
    # H5 (#89) — résolution JWK par `iss` (D18), alternative asymétrique au
    # secret partagé `narrate_jwt_secret` pour le mode strict.
    narrate_jwks_enabled: bool
    narrate_jwks_cache_ttl_seconds: float

    @property
    def table_jsonl_paths(self) -> list[Path]:
        """Tous les `.jsonl` directement sous `table_dir` (non-récursif)."""
        if not self.table_dir.exists():
            return []
        return sorted(p for p in self.table_dir.glob("*.jsonl") if p.is_file())


class ConfigError(RuntimeError):
    """Erreur de configuration détectée au démarrage — fail-fast."""


def _env_path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default))


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} doit être un entier, reçu {raw!r}") from exc


def _env_csv(name: str) -> list[str] | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    return [item.strip() for item in raw.split(",") if item.strip()]


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, str(default))
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} doit être un nombre, reçu {raw!r}") from exc


def _env_choice(name: str, default: str, choices: tuple[str, ...]) -> str:
    value = os.environ.get(name, default)
    if value not in choices:
        raise ConfigError(
            f"{name} doit être l'une de {choices}, reçu {value!r}"
        )
    return value


def _resolve_narrate_default_grant(auth_mode: str) -> int:
    """Résout `MUSES_NARRATE_DEFAULT_GRANT`, avec défaut dépendant du mode.

    H5 (#89, D-89.2) : en `strict`, une clé inconnue mais validement signée ne
    doit PAS recevoir de crédit gratuit — c'est la faille « n'importe quel
    token valide = 1000 crédits » que ce plan referme. Donc :
    - si la variable est EXPLICITEMENT posée (même à une valeur qui coïncide
      avec un défaut), on la respecte, quel que soit le mode ;
    - sinon (variable absente), le défaut dépend du mode : `0` en `strict`
      (accès réel = provisionnement explicite via `WalletStore.credit()` ou
      l'endpoint admin), `1000` en `off`/`stub` (confort dev inchangé).

    On utilise `os.environ.get(name)` (pas `_env_int(name, default)`) car ce
    dernier ne peut pas distinguer "absente" de "égale au défaut" — ambiguïté
    sans conséquence pour les autres réglages, mais qui casserait ici le
    branchement par mode. Une valeur vide (`MUSES_NARRATE_DEFAULT_GRANT=` dans
    un `.env` chargé tel quel, ex. `docker-compose`/systemd `EnvironmentFile`)
    compte comme "absente", cohérent avec le `or None` déjà utilisé pour
    `MUSES_NARRATE_JWT_SECRET` un peu plus haut.
    """
    raw = os.environ.get("MUSES_NARRATE_DEFAULT_GRANT")
    if not raw:
        return 0 if auth_mode == "strict" else 1000
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(
            f"MUSES_NARRATE_DEFAULT_GRANT doit être un entier, reçu {raw!r}"
        ) from exc


def load_config() -> Settings:
    """Construit `Settings` depuis l'environnement et valide les invariants."""
    # Résolu en amont : `narrate_default_grant` a un défaut qui dépend du mode
    # (D-89.2, cf. `_resolve_narrate_default_grant`).
    narrate_auth_mode = _env_choice(
        "MUSES_NARRATE_AUTH_MODE", "off", ("off", "stub", "strict"),
    )
    settings = Settings(
        table_dir=_env_path("MUSES_TABLE_DIR", "tables"),
        feedback_dir=_env_path("MUSES_FEEDBACK_DIR", "feedback"),
        snapshot_dir=_env_path("MUSES_SNAPSHOT_DIR", "snapshots"),
        admin_token=os.environ.get("MUSES_ADMIN_TOKEN") or None,
        signature_mode=_env_choice(
            "MUSES_SIGNATURE_MODE", "stub", ("stub", "strict"),
        ),  # type: ignore[arg-type]
        signature_max_age_seconds=_env_int("MUSES_SIGNATURE_MAX_AGE_SECONDS", 300),
        encoder=_env_choice(
            "MUSES_ENCODER", "stub", ("stub", "sentence_transformer"),
        ),  # type: ignore[arg-type]
        encoder_model=os.environ.get(
            "MUSES_ENCODER_MODEL", "paraphrase-multilingual-MiniLM-L12-v2",
        ),
        stub_encoder_dim=_env_int("MUSES_STUB_ENCODER_DIM", 16),
        bind_host=os.environ.get("MUSES_BIND_HOST", "127.0.0.1"),
        bind_port=_env_int("MUSES_BIND_PORT", 8000),
        rate_limit_per_minute=_env_int("MUSES_RATE_LIMIT_PER_MINUTE", 60),
        log_level=os.environ.get("MUSES_LOG_LEVEL", "INFO").upper(),
        log_format=_env_choice(
            "MUSES_LOG_FORMAT", "text", ("text", "json"),
        ),  # type: ignore[arg-type]
        narrate_auth_mode=narrate_auth_mode,  # type: ignore[arg-type]
        narrate_jwt_secret=os.environ.get("MUSES_NARRATE_JWT_SECRET") or None,
        narrate_jwt_algorithm=os.environ.get("MUSES_NARRATE_JWT_ALGORITHM", "HS256"),
        narrate_jwt_issuers=_env_csv("MUSES_NARRATE_JWT_ISSUERS"),
        narrate_default_grant=_resolve_narrate_default_grant(narrate_auth_mode),
        narrate_cors_origins=_env_csv("MUSES_NARRATE_CORS_ORIGINS"),
        narrate_jwks_enabled=_env_bool("MUSES_NARRATE_JWKS_ENABLED", False),
        narrate_jwks_cache_ttl_seconds=_env_float(
            "MUSES_NARRATE_JWKS_CACHE_TTL_SECONDS", 3600.0
        ),
    )

    _validate(settings)
    return settings


def _validate(s: Settings) -> None:
    """Refuse de démarrer si une combinaison dangereuse est détectée."""
    if not s.table_dir.exists():
        raise ConfigError(
            f"MUSES_TABLE_DIR n'existe pas: {s.table_dir}. "
            "Lance d'abord `python scripts/bootstrap_initial_cell.py` ou créé le dossier."
        )

    bind_public = s.bind_host not in ("127.0.0.1", "localhost", "::1")
    if bind_public:
        if s.admin_token is None:
            raise ConfigError(
                "MUSES_ADMIN_TOKEN doit être défini quand le service est bind "
                f"sur une interface publique ({s.bind_host!r}). "
                "Sinon /v1/admin/coverage n'aurait aucune protection."
            )
        if s.signature_mode == "stub":
            # Avertit fort mais ne bloque pas — la vérif crypto réelle peut
            # ne pas être encore implémentée. Log très visible.
            logging.getLogger("muses.config").warning(
                "MUSES_SIGNATURE_MODE=stub avec bind public %s:%d — "
                "les signatures ActivityPub ne sont PAS vérifiées cryptographiquement. "
                "Ne pas utiliser en production ouverte.",
                s.bind_host, s.bind_port,
            )

    if (
        s.narrate_auth_mode == "strict"
        and not s.narrate_jwt_secret
        and not s.narrate_jwks_enabled
    ):
        raise ConfigError(
            "MUSES_NARRATE_AUTH_MODE=strict exige soit MUSES_NARRATE_JWT_SECRET "
            "(secret HS256 ou clé publique PEM RS256 statique), soit "
            "MUSES_NARRATE_JWKS_ENABLED=true (vérification asymétrique via JWK "
            "résolu par iss, D18)."
        )

    if s.narrate_jwks_enabled and not s.narrate_jwt_issuers:
        raise ConfigError(
            "MUSES_NARRATE_JWKS_ENABLED=true exige MUSES_NARRATE_JWT_ISSUERS "
            "(liste blanche d'issuers) — sans elle, la résolution JWK fetch "
            "n'importe quel domaine passé en iss (risque SSRF)."
        )

    if s.narrate_auth_mode == "strict" and s.admin_token is None:
        # Revue de code #89 (avertissement) : le portefeuille /narrate est
        # toujours monté hors mode `off` (`_build_narrate_auth`), donc
        # `POST /v1/admin/narrate/credit` est toujours exposé en strict. Sans
        # admin_token, `_check_admin` est un no-op (cf. `muses/api/admin.py`) :
        # un faucet de crédits ouvert à tout appelant, annulant le contrôle
        # d'accès que `default_grant=0` est censé apporter.
        raise ConfigError(
            "MUSES_NARRATE_AUTH_MODE=strict exige MUSES_ADMIN_TOKEN — sans lui, "
            "POST /v1/admin/narrate/credit n'a aucune protection et permet de "
            "provisionner n'importe quel wallet_key sans authentification."
        )

    if s.narrate_auth_mode == "strict" and s.narrate_default_grant > 0:
        # Ne bloque pas — c'est un choix produit valide (D-89.2 le documente
        # comme alternative), mais il annule le contrôle d'accès réel que
        # `strict` est censé apporter : n'importe quel token validement signé
        # reçoit alors `narrate_default_grant` crédits gratuits au premier
        # appel. Averti fort, comme le garde `signature_mode=stub` ci-dessus.
        logging.getLogger("muses.config").warning(
            "MUSES_NARRATE_AUTH_MODE=strict avec MUSES_NARRATE_DEFAULT_GRANT=%d "
            "(> 0) — n'importe quel token validement signé reçoit ce crédit "
            "gratuit sur une clé inconnue : ce n'est PAS un vrai contrôle "
            "d'accès par utilisateur. Mettre MUSES_NARRATE_DEFAULT_GRANT=0 "
            "(défaut si la variable est omise) et provisionner explicitement "
            "via WalletStore.credit() / l'endpoint admin.",
            s.narrate_default_grant,
        )


def configure_logging(settings: Settings) -> None:
    """Initialise le logging selon la config. Idempotent."""
    level = getattr(logging, settings.log_level, logging.INFO)
    if settings.log_format == "json":
        fmt = '{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}'
    else:
        fmt = "%(asctime)s %(levelname)-7s %(name)s : %(message)s"
    logging.basicConfig(
        level=level,
        format=fmt,
        datefmt="%Y-%m-%dT%H:%M:%S%z",
        stream=sys.stderr,
        force=True,
    )
