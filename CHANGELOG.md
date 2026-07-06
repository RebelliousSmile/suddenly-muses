# Changelog

Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/). Versionnement sémantique.

## [Unreleased]

## [0.1.0] - 2026-07-06

### Added (ops Railway, post-merge sur main)

- `railway.toml` à la racine : config build (Nixpacks + bake du modèle sentence-transformer pendant le build) et deploy (startCommand uvicorn sur `$PORT`, healthcheck `/v1/health` à 90s, restart `ON_FAILURE` 3 retries, single replica).
- `aidd_docs/memory/infrastructure.md` § Déploiement Railway : procédure dashboard (volume sur `/data`, env vars complètes), premier boot, mise à jour des tables, limites Railway, reproductibilité sur Fly/Render/Heroku-likes.
- Closes #73.

### Added (pré-MVP, branche `claude/ml-table-selection-algorithm-WdSdd`)

- Service Muses complet : schémas Pydantic des rows, I/O JSONL append-only, index SQLite FTS5, cache embeddings `.npy`, pipeline d'ingestion avec validation et stub signature.
- Pipeline 4 étages CPU-only : sélecteur (tag matching + fallback hiérarchique), pondérateur cosinus, recombinateur non-génératif, filtreur best-of-N.
- API HTTP FastAPI : endpoints `/v1/suggest/{dialogue,action,description,thought,video_prompt}`, `/v1/analyze/{consistency_scene,consistency_session,summary,federated_links}`, `/v1/feedback/signal`, `/v1/admin/coverage`, `/v1/health`.
- `MusesClient` Python avec mode dégradé `MusesUnavailable` sur timeout / 5xx.
- Boucle de feedback : event log JSONL, trust contextuel Beta reputation par (user, axis, value), profil de style auteur, online learning v0, mode challenge avec malus sur rows familières, anti-sleeper, méta-suggestions, snapshots/rollback.
- Pipeline de mining bootstrap : adapter d'anonymisation (regex fallback ou spaCy), extracteur d'entités lexicon-based, classifieur de beats heuristique, script `bootstrap_initial_cell.py` qui peuple la cellule prioritaire (`medieval_fantastique × combat × hostile × solennel × colere`) avec 54 fragments + 6 beats + 11 entités.
- Documentation théorique complète : `philosophy.md`, `architecture.md`, `architecture-tables-ml.md`, `style-coaching.md`, `learning-and-trust.md`, `technical-plan.md`, `infrastructure.md`, `DECISIONS.md`, `LESSONS.md`, `external/axes-and-tags.md`, `external/data-format.md`, `external/use-cases.md`.

### Added (`/narrate` — relais narration Muse, H0 à H5, #82-#89)

- H0+H1 : contrat `schema.json`, stub best-of-N (#82).
- H2 : `LLMNarrator`, génération best-of-N via provider réel (#85).
- H3 : auth session + métrage. H4 : durcissement (#86, #87).
- H0 finalisé : vrai `schema.json` de CN, conformité du contrat (#83).
- H5 : provisioning/vérification de token Muse pour `/narrate` strict — résolution JWK par `iss` (D18), `MUSES_ADMIN_TOKEN` requis en strict, `narrate_default_grant=0` par défaut en strict, algorithme JWKS forcé à RS256 (#89).

### Added (tests)

- Suite e2e Hermes : runner local full-config et couverture qualité ML.

### Changed

- **Pivot architectural** : abandon de l'approche LoRA fine-tune au profit de tables curées + ML léger CPU-only. Cf. `DECISIONS.md` D01.
- Cinq axes contextuels canoniques (`univers`, `situation`, `rapport_initial`, `voix`, `emotion_dominante`) — extension du triplet initial pour capturer rapport et émotion comme dimensions distinctes.
- Identifiants normalisés en ASCII snake_case sans accent (`medieval_fantastique`, `narquois`, `colere`…).
- Anonymisation : listes `disable=` spécifiques par modèle spaCy (FR/EN) au chargement — évite un crash sur un modèle sans composant `tagger`.
- Playground : client `httpx` singleton au niveau module au lieu d'une instance par appel.

### Removed

- Stack pré-pivot : gateway FastAPI Railway, RunPod GPU, Cloudflare R2, providers Together.ai/Fireworks.ai, scripts d'entraînement Axolotl, tests d'évaluation LoRA.
- Docs mémoire LoRA-era purgées (11 fichiers dans `aidd_docs/memory/external/`).

### Fixed

- Correctifs suite à revue de code (durcissements divers).
- `crawl_rpv` : timeout de 10s ajouté sur tous les appels `requests.get()` (durcissement réseau).

### Security

- Authentification ActivityPub : stub de parsing pour le MVP, vérification cryptographique RSA-SHA256 documentée comme spec M4 dans `infrastructure.md`.
- Aucune dépendance à des providers d'inférence commerciale.
- `/narrate` strict : authentification JWT/JWKS avec allowlist d'`iss` (anti-SSRF), fail-closed si ni secret ni JWKS+issuers, `MUSES_ADMIN_TOKEN` désormais obligatoire en strict (sinon le faucet de crédits admin reste ouvert), algorithme JWKS forcé à `RS256`.
