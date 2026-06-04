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


def _env_choice(name: str, default: str, choices: tuple[str, ...]) -> str:
    value = os.environ.get(name, default)
    if value not in choices:
        raise ConfigError(
            f"{name} doit être l'une de {choices}, reçu {value!r}"
        )
    return value


def load_config() -> Settings:
    """Construit `Settings` depuis l'environnement et valide les invariants."""
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
        narrate_auth_mode=_env_choice(
            "MUSES_NARRATE_AUTH_MODE", "off", ("off", "stub", "strict"),
        ),  # type: ignore[arg-type]
        narrate_jwt_secret=os.environ.get("MUSES_NARRATE_JWT_SECRET") or None,
        narrate_jwt_algorithm=os.environ.get("MUSES_NARRATE_JWT_ALGORITHM", "HS256"),
        narrate_jwt_issuers=_env_csv("MUSES_NARRATE_JWT_ISSUERS"),
        narrate_default_grant=_env_int("MUSES_NARRATE_DEFAULT_GRANT", 1000),
        narrate_cors_origins=_env_csv("MUSES_NARRATE_CORS_ORIGINS"),
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

    if s.narrate_auth_mode == "strict" and not s.narrate_jwt_secret:
        raise ConfigError(
            "MUSES_NARRATE_AUTH_MODE=strict exige MUSES_NARRATE_JWT_SECRET "
            "(secret HS256 ou clé publique PEM RS256)."
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
