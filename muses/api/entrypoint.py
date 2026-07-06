"""Point d'entrée ASGI prêt pour `uvicorn muses.api.entrypoint:app`.

Lit la configuration depuis l'environnement (cf. `.env.example`), initialise
le logging, construit l'encodeur et l'app FastAPI. Expose `app` au niveau
module pour que les serveurs ASGI standards le trouvent.

Toute erreur de configuration au démarrage lève `ConfigError` et empêche
le démarrage — fail-fast préférable à un service qui sert silencieusement
des résultats incorrects.
"""

from __future__ import annotations

import logging

from muses.api.server import create_app
from muses.config import Settings, configure_logging, load_config
from muses.tables.embeddings import (
    DEFAULT_MODEL,
    Encoder,
    SentenceTransformerEncoder,
    StubEncoder,
)


def _build_encoder(settings: Settings) -> Encoder:
    if settings.encoder == "sentence_transformer":
        model = settings.encoder_model or DEFAULT_MODEL
        return SentenceTransformerEncoder(model_name=model)
    return StubEncoder(dim=settings.stub_encoder_dim)


def _build_narrate_auth(settings: Settings):
    """Construit (session_auth, wallet) pour /narrate selon le mode (H3).

    `off` → (None, None) : relais ouvert, pas de métrage.
    """
    if settings.narrate_auth_mode == "off":
        return None, None

    from muses.narrate import (
        JwtSessionVerifier,
        StubSessionVerifier,
        WalletStore,
        make_jwks_key_lookup,
        make_session_dependency,
    )

    if settings.narrate_auth_mode == "stub":
        verifier = StubSessionVerifier()
    elif settings.narrate_jwks_enabled:  # strict — JWK résolu par iss (D18), pas de secret
        verifier = JwtSessionVerifier(
            key_lookup=make_jwks_key_lookup(
                issuers=settings.narrate_jwt_issuers,
                cache_ttl_seconds=settings.narrate_jwks_cache_ttl_seconds,
            ),
            # Revue de code #89 (avertissement) : `jwks.py:key_lookup` renvoie
            # toujours "RS256" (clés publiques RSA résolues depuis le JWK) —
            # jamais `settings.narrate_jwt_algorithm` (qui ne concerne que la
            # branche secret statique ci-dessous, défaut "HS256"). Réutiliser
            # ce réglage ici créerait un mismatch algorithmique silencieux si
            # l'opérateur oublie MUSES_NARRATE_JWT_ALGORITHM=RS256 (panne
            # d'auth totale : `session.py` rejette alors chaque token).
            algorithms=["RS256"],
            issuers=settings.narrate_jwt_issuers,
        )
    else:  # strict — secret partagé validé par load_config (HS256/dev ou PEM statique)
        verifier = JwtSessionVerifier(
            key=settings.narrate_jwt_secret,  # type: ignore[arg-type]
            algorithms=[settings.narrate_jwt_algorithm],
            issuers=settings.narrate_jwt_issuers,
        )
    wallet = WalletStore(
        settings.feedback_dir / "narrate_wallet.sqlite",
        default_grant=settings.narrate_default_grant,
    )
    return make_session_dependency(verifier), wallet


def _build_app(settings: Settings):
    logger = logging.getLogger("muses.entrypoint")
    table_paths = settings.table_jsonl_paths
    if not table_paths:
        logger.warning(
            "Aucun fichier .jsonl trouvé sous %s — le service répondra "
            "0 suggestion sur toutes les requêtes. Bootstrap manquant ?",
            settings.table_dir,
        )
    logger.info(
        "Démarrage Muses : tables=%d, encoder=%s, signature_mode=%s, admin=%s, rate_limit=%d/min",
        len(table_paths),
        settings.encoder,
        settings.signature_mode,
        "set" if settings.admin_token else "OPEN",
        settings.rate_limit_per_minute,
    )

    narrate_session_auth, narrate_wallet = _build_narrate_auth(settings)

    return create_app(
        tables=table_paths,
        encoder=_build_encoder(settings),
        event_log_path=settings.feedback_dir / "events.jsonl",
        trust_db_path=settings.feedback_dir / "trust.sqlite",
        instance_db_path=settings.feedback_dir / "instance_reputation.sqlite",
        style_db_path=settings.feedback_dir / "style_profile.sqlite",
        learner_db_path=settings.feedback_dir / "online_learner.sqlite",
        admin_token=settings.admin_token,
        signature_mode=settings.signature_mode,
        signature_max_age_seconds=settings.signature_max_age_seconds,
        rate_limit_per_minute=settings.rate_limit_per_minute,
        narrate_session_auth=narrate_session_auth,
        narrate_wallet=narrate_wallet,
        narrate_cors_origins=settings.narrate_cors_origins,
    )


# Chargé à l'import — uvicorn appelle `import muses.api.entrypoint`
# et utilise `app`. Toute erreur de config remonte ici → uvicorn refuse
# de démarrer, comportement souhaité.
_settings = load_config()
configure_logging(_settings)
app = _build_app(_settings)
