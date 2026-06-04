"""T21 — Serveur HTTP FastAPI du service Muses.

Endpoints exposés :
- GET /v1/health — liveness check sans auth
- POST /v1/suggest/{dialogue,action,description,thought,video_prompt}
  Toutes signées par signature ActivityPub.
- POST /v1/feedback/signal — capture des 5 signaux UI [signature requise]
- POST /v1/analyze/{consistency_scene,consistency_session,summary,federated_links}
  [signature requise]
- GET /v1/admin/coverage — carte de couverture admin [token admin]

L'orchestrateur, l'encodeur, les stores et l'event log sont injectés à la
création de l'app pour permettre les tests et le déploiement.
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from pathlib import Path
from time import monotonic
from typing import Callable, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from muses.analysis.coherence import (
    analyze_scene_coherence,
    analyze_session_coherence,
)
from muses.analysis.federated_links import find_federated_links
from muses.analysis.summary import generate_session_summary
from muses.api.admin import create_admin_router
from muses.api.auth import ParsedSignature, require_signature_stub
from muses.api.schemas import SuggestRequest, SuggestResponse, SuggestionItem
from muses.api.signature import HttpKeyResolver, KeyResolver, make_strict_dependency
from muses.feedback.events import SIGNAL_TYPES, EventLog, FeedbackSignal, SignalType
from muses.feedback.instance_reputation import InstanceReputationStore
from muses.feedback.online_learning import OnlineLearner
from muses.feedback.style_profile import StyleProfileStore
from muses.feedback.trust import TrustStore
from muses.narrate import (
    LLMNarrator,
    Narrator,
    SessionClaims,
    WalletStore,
    create_narrate_router,
)
from muses.pipeline.orchestrator import Orchestrator
from muses.tables.embeddings import Encoder, StubEncoder
from pipelines.evaluation.providers import ProviderError


logger = logging.getLogger("muses.api")


SignatureMode = Literal["stub", "strict"]


class FeedbackSignalRequest(BaseModel):
    """Payload du POST /v1/feedback/signal."""

    signal: SignalType
    user_id: str
    instance_id: str
    feature: str
    row_id: str
    contributor_user_id: str | None = None
    contributor_instance_id: str | None = None
    context_tags: dict[str, list[str]] = Field(default_factory=dict)
    edited_text: str | None = None


class FeedbackSignalResponse(BaseModel):
    """Réponse du POST /v1/feedback/signal."""

    recorded: bool
    signal: SignalType


class HealthResponse(BaseModel):
    """Réponse du GET /v1/health."""

    status: Literal["ok"]
    tables_count: int
    encoder_dim: int
    feedback_enabled: bool
    signature_mode: SignatureMode


class SceneCoherenceRequest(BaseModel):
    scene_fragments: list[str]


class CoherenceIssueResponse(BaseModel):
    severity: str
    fragment_index: int
    description: str


class SceneCoherenceResponse(BaseModel):
    n_issues: int
    issues: list[CoherenceIssueResponse]


class SessionCoherenceRequest(BaseModel):
    scenes: list[list[str]]


class SessionCoherenceResponse(BaseModel):
    n_scenes: int
    n_issues: int
    distinct_beats: list[str]
    issues: list[dict]


class SummaryResponse(BaseModel):
    summary: str


class FederatedLinksRequest(BaseModel):
    session_characters: dict[str, str]
    public_characters: dict[str, str]
    threshold: float = Field(0.3, ge=0.0, le=1.0)


class FederatedLinkItem(BaseModel):
    session_character: str
    public_character_id: str
    similarity: float
    confidence: str


class FederatedLinksResponse(BaseModel):
    suggestions: list[FederatedLinkItem]


# ---------------------------------------------------------------------------
# Rate limiting — implémentation minimale in-process par IP
# ---------------------------------------------------------------------------


class _SlidingWindowLimiter:
    """Limite N requêtes par minute et par client IP. In-process, sans Redis.

    Pour un déploiement multi-worker, à remplacer par slowapi+redis ou par un
    rate-limiter au niveau du reverse proxy (nginx/Caddy). Cette version
    suffit pour un single-worker MVP.
    """

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._buckets: dict[str, deque[float]] = defaultdict(deque)

    def acquire(self, client_id: str) -> bool:
        if self.per_minute <= 0:
            return True
        now = monotonic()
        bucket = self._buckets[client_id]
        cutoff = now - 60.0
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= self.per_minute:
            return False
        bucket.append(now)
        return True


def _enable_sqlite_wal(db_paths: list[Path]) -> None:
    """Active WAL + synchronous=NORMAL sur les SQLite stores.

    WAL mode permet lectures concurrentes pendant les écritures — important
    quand uvicorn lance plusieurs workers ou quand l'admin endpoint lit la
    coverage en même temps qu'un signal arrive.
    """
    import sqlite3
    for path in db_paths:
        if not path.exists():
            # Le store crée son schéma au premier use ; on saute si pas créé.
            continue
        with sqlite3.connect(path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")


def create_app(
    *,
    tables: list[Path],
    encoder: Encoder | None = None,
    event_log_path: Path | None = None,
    trust_db_path: Path | None = None,
    instance_db_path: Path | None = None,
    style_db_path: Path | None = None,
    learner_db_path: Path | None = None,
    admin_token: str | None = None,
    signature_mode: SignatureMode = "stub",
    signature_max_age_seconds: int = 300,
    key_resolver: KeyResolver | None = None,
    rate_limit_per_minute: int = 0,
    narrator: Narrator | None = None,
    narrate_session_auth: Callable[[Request], SessionClaims] | None = None,
    narrate_wallet: WalletStore | None = None,
    narrate_cors_origins: list[str] | None = None,
) -> FastAPI:
    """Construit l'application FastAPI complète.

    - `signature_mode="stub"` : parse uniquement, pas de crypto (dev/tests).
    - `signature_mode="strict"` : vérif RSA-SHA256 + résolution acteur + anti-replay.
    - `key_resolver` : injectable pour les tests (sinon `HttpKeyResolver` par défaut).
    - `rate_limit_per_minute=0` : pas de rate limit. Sinon limit par IP.
    """
    encoder = encoder or StubEncoder(dim=16)
    orchestrator = Orchestrator(tables=tables, encoder=encoder)

    event_log = EventLog(event_log_path) if event_log_path else None
    trust_store = TrustStore(trust_db_path) if trust_db_path else None
    instance_store = InstanceReputationStore(instance_db_path) if instance_db_path else None
    style_store = StyleProfileStore(style_db_path) if style_db_path else None
    learner = OnlineLearner(learner_db_path) if learner_db_path else None

    sqlite_paths = [
        p for p in [trust_db_path, instance_db_path, style_db_path, learner_db_path]
        if p is not None
    ]
    _enable_sqlite_wal(sqlite_paths)

    if signature_mode == "strict":
        resolver = key_resolver or HttpKeyResolver()
        signature_dep: Callable[..., ParsedSignature] = make_strict_dependency(
            resolver, max_age_seconds=signature_max_age_seconds,
        )
    else:
        signature_dep = require_signature_stub

    limiter = _SlidingWindowLimiter(rate_limit_per_minute)

    app = FastAPI(
        title="Muses",
        description="Service mutualisé d'assistance créative pour le Fediverse Suddenly",
        version="0.0.0-pre-mvp",
    )

    # H4 — CORS opt-in restreint au domaine choix-narratifs. Désactivé par
    # défaut : l'appel CN→Hub est serveur-à-serveur (CORS = navigateur), donc
    # généralement inutile. Activé uniquement si des origines sont fournies.
    if narrate_cors_origins:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=narrate_cors_origins,
            allow_methods=["POST"],
            allow_headers=["Authorization", "Content-Type"],
        )

    @app.middleware("http")
    async def _rate_limit_mw(request: Request, call_next):
        if rate_limit_per_minute > 0:
            client_id = request.client.host if request.client else "unknown"
            if not limiter.acquire(client_id):
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded"},
                    headers={"Retry-After": "60"},
                )
        return await call_next(request)

    @app.get("/v1/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            tables_count=len(tables),
            encoder_dim=encoder.dim,
            feedback_enabled=event_log is not None,
            signature_mode=signature_mode,
        )

    def _serve_generation(req: SuggestRequest, expected: str) -> SuggestResponse:
        if req.feature != expected:
            raise HTTPException(
                status_code=400,
                detail=f"This endpoint serves only feature={expected!r}, got {req.feature!r}",
            )
        result = orchestrator.generate(
            context_text=req.context_text,
            context_tags=req.context_tags,
            n_candidates=req.n_candidates,
            top_n=req.top_n,
            mode=req.mode,
            user_id=req.user_id,
        )
        return SuggestResponse(
            suggestions=[
                SuggestionItem(
                    text=c.text,
                    source_row_ids=c.source_row_ids,
                    source_scores=c.source_scores,
                )
                for c in result.candidates
            ],
            relaxed_axes=result.relaxed_axes,
            selected_table_count=len(result.selected_tables),
            weighted_count=result.weighted_count,
        )

    @app.post("/v1/suggest/dialogue", response_model=SuggestResponse)
    def suggest_dialogue(
        req: SuggestRequest,
        sig: ParsedSignature = Depends(signature_dep),
    ) -> SuggestResponse:
        return _serve_generation(req, "dialogue")

    @app.post("/v1/suggest/action", response_model=SuggestResponse)
    def suggest_action(
        req: SuggestRequest,
        sig: ParsedSignature = Depends(signature_dep),
    ) -> SuggestResponse:
        return _serve_generation(req, "action")

    @app.post("/v1/suggest/description", response_model=SuggestResponse)
    def suggest_description(
        req: SuggestRequest,
        sig: ParsedSignature = Depends(signature_dep),
    ) -> SuggestResponse:
        return _serve_generation(req, "description")

    @app.post("/v1/suggest/thought", response_model=SuggestResponse)
    def suggest_thought(
        req: SuggestRequest,
        sig: ParsedSignature = Depends(signature_dep),
    ) -> SuggestResponse:
        return _serve_generation(req, "thought")

    @app.post("/v1/suggest/video_prompt", response_model=SuggestResponse)
    def suggest_video_prompt(
        req: SuggestRequest,
        sig: ParsedSignature = Depends(signature_dep),
    ) -> SuggestResponse:
        # T44 — pas de filtre best-of-N pour cette feature (cf. use-cases.md §4.4).
        # Pour MVP M5, on garde le même pipeline ; la spécialisation canvas-fixe
        # vient avec la curation dédiée des templates visuels.
        return _serve_generation(req, "video_prompt")

    @app.post("/v1/feedback/signal", response_model=FeedbackSignalResponse)
    def feedback_signal(
        req: FeedbackSignalRequest,
        sig: ParsedSignature = Depends(signature_dep),
    ) -> FeedbackSignalResponse:
        if event_log is None:
            raise HTTPException(
                status_code=503,
                detail="Feedback log not configured on this instance",
            )
        signal = FeedbackSignal(
            signal=req.signal,
            user_id=req.user_id,
            instance_id=req.instance_id,
            feature=req.feature,
            row_id=req.row_id,
            contributor_user_id=req.contributor_user_id,
            contributor_instance_id=req.contributor_instance_id,
            context_tags=req.context_tags,
            edited_text=req.edited_text,
        )
        event_log.append(signal)

        # Pipeline online : trust + learner + profil
        if trust_store is not None:
            trust_store.update_from_signal(signal)
        if learner is not None:
            learner.update_from_signal(signal)
        if style_store is not None and signal.signal in ("accept", "accept_edited"):
            style_store.observe(
                user_id=signal.user_id,
                row_id=signal.row_id,
                text=signal.edited_text,
            )
        logger.debug(
            "signal recorded user=%s row=%s feature=%s type=%s",
            signal.user_id, signal.row_id, signal.feature, signal.signal,
        )
        return FeedbackSignalResponse(recorded=True, signal=signal.signal)

    @app.post("/v1/analyze/consistency_scene", response_model=SceneCoherenceResponse)
    def analyze_consistency_scene_endpoint(
        req: SceneCoherenceRequest,
        sig: ParsedSignature = Depends(signature_dep),
    ) -> SceneCoherenceResponse:
        issues = analyze_scene_coherence(req.scene_fragments)
        return SceneCoherenceResponse(
            n_issues=len(issues),
            issues=[
                CoherenceIssueResponse(
                    severity=i.severity,
                    fragment_index=i.fragment_index,
                    description=i.description,
                )
                for i in issues
            ],
        )

    @app.post("/v1/analyze/consistency_session", response_model=SessionCoherenceResponse)
    def analyze_consistency_session_endpoint(
        req: SessionCoherenceRequest,
        sig: ParsedSignature = Depends(signature_dep),
    ) -> SessionCoherenceResponse:
        data = analyze_session_coherence(req.scenes)
        return SessionCoherenceResponse(**data)

    @app.post("/v1/analyze/summary", response_model=SummaryResponse)
    def analyze_summary_endpoint(
        req: SessionCoherenceRequest,
        sig: ParsedSignature = Depends(signature_dep),
    ) -> SummaryResponse:
        return SummaryResponse(summary=generate_session_summary(req.scenes))

    @app.post("/v1/analyze/federated_links", response_model=FederatedLinksResponse)
    def analyze_federated_links_endpoint(
        req: FederatedLinksRequest,
        sig: ParsedSignature = Depends(signature_dep),
    ) -> FederatedLinksResponse:
        suggestions = find_federated_links(
            req.session_characters,
            req.public_characters,
            encoder=encoder,
            threshold=req.threshold,
        )
        return FederatedLinksResponse(
            suggestions=[
                FederatedLinkItem(
                    session_character=s.session_character,
                    public_character_id=s.public_character_id,
                    similarity=s.similarity,
                    confidence=s.confidence,
                )
                for s in suggestions
            ],
        )

    if tables:
        app.include_router(create_admin_router(tables=tables, admin_token=admin_token))

    # D-Hub-0 — relais narrateur /narrate, famille de routes distincte (sert CN,
    # aveugle au canon). Partage l'infra (app, rate-limit) sans la sémantique.
    # H2 : LLMNarrator par défaut ; CannedNarrator reste injectable (tests/red-team).
    # H3 : auth session + portefeuille injectés (None → ouvert, pas de débit).
    app.include_router(
        create_narrate_router(
            narrator or LLMNarrator(),
            session_auth=narrate_session_auth,
            wallet=narrate_wallet,
        )
    )

    @app.exception_handler(ProviderError)
    async def _provider_error_handler(request: Request, exc: ProviderError):
        # Échec du provider LLM → 502, aucun faux succès. Le débit (H3) n'a pas
        # encore eu lieu, donc rien à rembourser ici.
        from fastapi.responses import JSONResponse

        logger.warning("narrate provider error: %s", exc)
        return JSONResponse(
            status_code=502,
            content={"detail": f"narrator provider unavailable: {exc}"},
        )

    return app
