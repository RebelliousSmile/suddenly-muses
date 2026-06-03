# Campagne de test E2E Muse — Contrat + Qualité ML

> **For Hermes:** Execute task-by-task. Each task produces one commit.

**Goal:** Tester le service Muse en profondeur sur deux niveaux — (1) le **contrat HTTP** contre l'instance déployée `https://muse.suddenly.social`, et (2) la **qualité ML** (pertinence des suggestions, relâchement d'axes, mode challenge, boucle feedback, analyses) contre une instance correctement configurée. Isoler et documenter la dérive de config de la prod.

**Architecture:** Harnais `httpx`/`pytest` sous `tests/e2e/`, base URL paramétrable, signature en mode stub. Deux marqueurs pytest : `contract` (cible prod) et `ml` (cible instance pleine).

**Tech Stack:** Python 3.12, `httpx`, `pytest`, FastAPI (`muses.api.entrypoint:app`), `sentence-transformers`.

---

## Contexte (état constaté le 2026-06-03)

`GET https://muse.suddenly.social/v1/health` renvoie :

```json
{"status":"ok","tables_count":0,"encoder_dim":16,"feedback_enabled":true,"signature_mode":"stub"}
```

Lecture critique :
- **Service vivant et consommable** — contredit `aidd_docs/memory/deployment.md` et la décision D16 (« Phase 1 = pas de déploiement »). La doc est en retard sur la réalité ; ne pas s'y fier.
- `tables_count:0` + `encoder_dim:16` → l'instance prod tourne avec l'**encodeur stub** et **aucune table**, alors que `railway.toml` prescrit `MUSES_ENCODER=sentence_transformer` et `MUSES_TABLE_DIR=tables/bootstrap_cell_medfan_combat_hostile_solennel_colere`. **Dérive de config prod** → la qualité ML est non mesurable en l'état sur la prod.
- `signature_mode:stub` → header `Signature: keyId="x",signature="abc"` suffit (parsing seul, pas de vérif crypto).

Tables disponibles localement : **une seule cellule** — `tables/bootstrap_cell_medfan_combat_hostile_solennel_colere`.

Endpoints à couvrir (11) : `GET /v1/health` ; `POST /v1/suggest/{dialogue,action,description,thought,video_prompt}` ; `POST /v1/feedback/signal` ; `POST /v1/analyze/{consistency_scene,consistency_session,summary,federated_links}` ; `GET /v1/admin/coverage`.

---

## Task 1: Harnais de test E2E

**Objective:** Poser le socle de tests réutilisable (client, fixtures, marqueurs).

**Files:**
- Create: `tests/e2e/__init__.py`
- Create: `tests/e2e/conftest.py`
- Modify: `pyproject.toml` (déclarer les markers `contract` et `ml` + extra `[e2e]` si besoin de `httpx`)

**Changements:**
1. `conftest.py` : fixture `base_url` lue depuis `MUSES_BASE_URL` (défaut `https://muse.suddenly.social`).
2. Fixture `client` : `httpx.Client(base_url=..., timeout=30)`.
3. Helper `stub_sig_headers()` → `{"Signature": 'keyId="test",signature="stub",algorithm="rsa-sha256"'}`.
4. Fixture `admin_headers` lue depuis `MUSES_ADMIN_TOKEN` (skip propre si absent).
5. Helper `axial_tags()` retournant les tags de la cellule bootstrap (univers `medfan`, style `combat`, posture `hostile`, registre `solennel`, émotion `colere` — à confirmer en lisant le 1er objet du `.jsonl`).
6. Enregistrer markers `contract` et `ml` dans `pyproject.toml` (`[tool.pytest.ini_options] markers`).

**Vérification:** `pytest tests/e2e/ --collect-only` liste les fixtures sans erreur d'import.

**Commit:**
```bash
git add tests/e2e/__init__.py tests/e2e/conftest.py pyproject.toml
git commit -m "test(e2e): scaffold Muse end-to-end harness (httpx client, stub signature, markers)"
```

---

## Task 2: Tests de contrat — santé, auth, validation

**Objective:** Vérifier le contrat transversal contre la prod.

**Files:**
- Create: `tests/e2e/test_contract_core.py` (marqueur `contract`)

**Changements:**
1. `GET /v1/health` → 200, schéma `{status, tables_count, encoder_dim, feedback_enabled, signature_mode}` typé.
2. Auth : `POST /v1/suggest/dialogue` **sans** header `Signature` → **401**.
3. Auth : avec header `Signature` malformé (non parsable) → **401**.
4. Validation : `POST /v1/suggest/dialogue` avec body invalide (sans `context_text`) + signature stub → **422**.
5. Routing : `POST /v1/suggest/dialogue` avec `feature:"action"` dans le body → erreur attendue (mismatch feature/route).
6. Rate-limit : boucle > `MUSES_RATE_LIMIT_PER_MINUTE` (si exposé) → présence d'un **429** (test marqué `xfail` si la limite est désactivée en prod).

**Vérification:** `MUSES_BASE_URL=https://muse.suddenly.social pytest tests/e2e/test_contract_core.py -m contract -v` → tous verts (hors xfail documentés).

**Commit:**
```bash
git add tests/e2e/test_contract_core.py
git commit -m "test(e2e): contract tests for health, auth and validation against prod"
```

---

## Task 3: Tests de contrat — 11 endpoints (formes de réponse)

**Objective:** Couvrir chaque endpoint en mode contrat (statuts + forme), en tolérant les réponses dégradées dues à `tables_count:0`.

**Files:**
- Create: `tests/e2e/test_contract_endpoints.py` (marqueur `contract`)

**Changements:**
1. Paramétrer les 5 `POST /v1/suggest/{feature}` → 200, clés `{suggestions, relaxed_axes, selected_table_count, weighted_count}` présentes ; **assert souple** : `suggestions` peut être vide tant que `tables_count==0` (le documenter dans le test).
2. `POST /v1/feedback/signal` (signal `accept`) → 200 `{recorded:true, signal:"accept"}`.
3. Les 4 `POST /v1/analyze/*` → 200, clés-clés du schéma présentes (`n_issues`, `summary`, `suggestions`…).
4. `GET /v1/admin/coverage` avec token → 200 `{cells, total_cells}` ; sans token → 401/403.

**Vérification:** `pytest tests/e2e/test_contract_endpoints.py -m contract -v` → tous verts. Un commentaire en tête du fichier note que les `suggestions` vides sont attendues vu l'état prod.

**Commit:**
```bash
git add tests/e2e/test_contract_endpoints.py
git commit -m "test(e2e): contract coverage of all 11 Muse endpoints (degraded-tolerant)"
```

---

## Task 4: Constat de dérive de config prod

**Objective:** Documenter formellement l'écart entre `railway.toml` et l'état runtime, pour décision (livrable distinct, pas un fix silencieux).

**Files:**
- Create: `aidd_docs/memory/internal/finding-2026-06-03-prod-config-drift.md`

**Changements:**
1. Tableau : valeur attendue (`railway.toml`) vs valeur observée (`/v1/health`) pour `encoder` et `tables`.
2. Hypothèses : variables d'env non appliquées côté dashboard Railway, volume `/data` vide, ou `MUSES_TABLE_DIR` pointant sur un dossier absent dans l'image.
3. Impact : qualité ML non testable en prod ; suggestions vides.
4. Reco : vérifier les env vars Railway + le mount `/data` + la présence des `.jsonl` dans l'image. **Ne pas redéployer dans ce plan.**

**Vérification:** Le fichier existe et liste au moins 3 hypothèses + 1 reco actionnable.

**Commit:**
```bash
git add aidd_docs/memory/internal/finding-2026-06-03-prod-config-drift.md
git commit -m "docs(finding): document prod config drift (stub encoder, 0 tables vs railway.toml)"
```

---

## Task 5: Instance pleine locale pour le volet ML

**Objective:** Fournir une cible correctement configurée (vrai encodeur + tables) pour les tests de qualité.

**Files:**
- Create: `scripts/run_muse_full_local.sh` (lance l'instance ML-complète)
- Create: `tests/e2e/.env.ml.example`

**Changements:**
1. Script : `export MUSES_ENCODER=sentence_transformer`, `MUSES_TABLE_DIR=tables/bootstrap_cell_medfan_combat_hostile_solennel_colere`, `MUSES_SIGNATURE_MODE=stub`, `MUSES_BIND_PORT=8001` puis `uvicorn muses.api.entrypoint:app --port 8001`.
2. `.env.ml.example` documente les variables et l'extra `pip install -e .[api,embeddings]`.
3. Le script échoue proprement si le dossier de tables est vide.

**Vérification:** Lancement → `curl http://127.0.0.1:8001/v1/health` renvoie `tables_count>0` et `encoder_dim>16` (dimension du vrai modèle). Consigner la valeur observée.

**Commit:**
```bash
git add scripts/run_muse_full_local.sh tests/e2e/.env.ml.example
git commit -m "test(e2e): add full-config local Muse runner for ML-quality testing"
```

---

## Task 6: Tests de qualité ML

**Objective:** Mesurer la pertinence réelle contre l'instance pleine (`MUSES_BASE_URL=http://127.0.0.1:8001`).

**Files:**
- Create: `tests/e2e/test_ml_quality.py` (marqueur `ml`)

**Changements:**
1. `suggest/dialogue` avec tags **alignés** sur la cellule bootstrap → `suggestions` **non vide**, `source_row_ids` peuplés, `selected_table_count>0`.
2. Relâchement d'axes : tags partiellement hors cellule → `relaxed_axes` non vide (le service relâche pour servir).
3. Mode `challenge` avec `user_id` → réponses distinctes du mode `confort` (assert sur divergence des `source_row_ids`).
4. Boucle feedback : `accept` puis ré-`suggest` même contexte → vérifier que le signal est pris en compte (pondération/trust modifiés ; assert tolérant).
5. Analyses sémantiques : `consistency_scene` sur fragments volontairement incohérents → `n_issues>0` ; `federated_links` avec persos proches → au moins 1 `suggestion` au-dessus du seuil.

**Vérification:** `MUSES_BASE_URL=http://127.0.0.1:8001 pytest tests/e2e/test_ml_quality.py -m ml -v` → verts contre l'instance pleine.

**Commit:**
```bash
git add tests/e2e/test_ml_quality.py
git commit -m "test(e2e): ML-quality tests (relevance, axis relaxation, challenge, feedback, analysis)"
```

---

## Task 7: Synthèse de campagne

**Objective:** Rapport unique prod (dégradée) vs locale (pleine).

**Files:**
- Create: `aidd_docs/memory/internal/report-2026-06-03-muse-e2e.md`

**Changements:**
1. Tableau récap : endpoint × (résultat contrat prod / résultat ML local).
2. Liste des écarts prod (renvoie au finding Task 4).
3. Commande de relance : marqueurs `contract` (prod) et `ml` (local).

**Vérification:** Le rapport référence les 7 tâches et les deux cibles d'URL.

**Commit:**
```bash
git add aidd_docs/memory/internal/report-2026-06-03-muse-e2e.md
git commit -m "docs(report): Muse E2E campaign summary (prod contract + local ML quality)"
```
