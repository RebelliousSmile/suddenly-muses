# Payload — issues à créer dans `muse-challenge`

> Ces 7 issues ont d'abord été créées par erreur dans `suddenly-muses` (#75-#81)
> faute d'accès à `muse-challenge` dans la session. Destination correcte =
> `muse-challenge`. Une fois recréées là-bas, **fermer** #75-#81 dans
> `suddenly-muses` avec renvoi, et mettre à jour
> `2026-06-03-hermes-test-plan-verdict.md` avec les nouveaux numéros.
>
> Chaque bloc ci-dessous = `title` + `body` d'une issue.

---

## 1. EPIC

**Title :** `[TEST][EPIC] Plan de test hermes — redressement post-pivot (cibler le service muses/ réel)`

**Body :**

```md
## Contexte

`hermes` est un agent de test autonome. Son plan de test (phases 3→7) cible la stack
**LoRA / fine-tune Qwen2.5 / Axolotl / Together.ai / GPU / K8s / API OpenAI / open-source community**.

Cette stack a été **abandonnée** par la décision **D01** (pivot LoRA → tables+ML, mai 2026).
Les phases 3-7 testent donc un projet qui n'existe plus.

- `phase7_community.md` a tous ses critères cochés `[x]` ("1000+ stars", "500+ Discord") — ni réels, ni testables.
- Les `challenge_phase*.md` ne valident que la structure du document, jamais le code réel.
- L'application réelle est `muses/` : construite (M0-M5, issues suddenly-muses#67-#73 fermées), 44 modules, 37 fichiers de tests.

## Décision

- ❌ Ne PAS faire phase 7 (ni 3-6) : architecture morte.
- ✅ Tester le service `muses/` réel en validation comportementale / E2E, contre les contrats réels.

## Sous-tâches

- [ ] Smoke E2E suggest_dialogue (T25)
- [ ] Pipeline 4 étages — contrats & comportement
- [ ] Ingestion & tables
- [ ] Boucle de feedback
- [ ] API & Auth ActivityPub
- [ ] Client dégradé & analyse

## Hygiène

Archiver / marquer OBSOLÈTES `aidd_docs/tasks/phase{3..7}_*.md` et `aidd_docs/reviews/challenge_phase{3..7}.md`.
```

---

## 2. Smoke E2E

**Title :** `[TEST] Smoke E2E réel — suggest_dialogue de bout en bout (T25)`

**Body :**

```md
Parent : EPIC

## Objectif
Valider le chemin critique MVP réellement exécuté : instance Suddenly mockée → service Muses → réponse exploitable.

## Surface
- `muses/api/server.py` → `POST /v1/suggest/dialogue`
- `muses/pipeline/orchestrator.py`
- `muses/client.py`
- tables peuplées (cellule contextuelle, cf. T15)

## À vérifier
- [ ] Démarrage serveur + `GET /v1/health` OK.
- [ ] `suggest/dialogue` avec contexte 5 axes renvoie ≥1 suggestion non vide.
- [ ] Traçabilité : suggestion → row(s) tirée(s) (zéro génération autoregressive).
- [ ] Cellule vide → fallback hiérarchique propre (pas de 500).
- [ ] Contexte invalide → 4xx clair, pas de crash.

Réf : technical-plan T20-T25, use-cases §2.1.
```

---

## 3. Pipeline 4 étages

**Title :** `[TEST] Pipeline 4 étages — contrats & comportement`

**Body :**

```md
Parent : EPIC

## Objectif
Exercer le pipeline réel ; vérifier le rôle de chaque étage (D03) et l'étage 3 strictement sans modèle (D04).

## Surface
- `muses/pipeline/{selector,weighter,recombiner,filter,orchestrator}.py`

## À vérifier
- [ ] Étage 1 : tag matching strict puis fallback hiérarchique.
- [ ] Étage 2 : ordre cohérent avec la similarité cosinus.
- [ ] Étage 3 : slots typés déterministes, variantes d'accord = rows distinctes, aucune glue générative (D04).
- [ ] Étage 4 : passthrough top-N conforme.
- [ ] Challenge vs confort (`test_challenge_mode.py`) : sorties divergentes, pas de collapse (D11).
- [ ] Orchestrateur : panne d'un étage → comportement défini.

Réf : architecture-tables-ml, D03/D04/D11.
```

---

## 4. Ingestion & tables

**Title :** `[TEST] Ingestion & tables — JSONL append-only / SQLite FTS5 / embeddings`

**Body :**

```md
Parent : EPIC

## Objectif
Valider intégrité stockage + ingestion sur cas réels (round-trip, concurrence, données sales).

## Surface
- `muses/tables/{jsonl_io,sqlite_index,embeddings}.py`
- `muses/ingestion/pipeline.py`
- `muses/schemas/{row,tags,content}.py`

## À vérifier
- [ ] Round-trip JSONL sans perte ni réordonnancement.
- [ ] Index FTS5 reconstruit = cohérent avec le contenu.
- [ ] Embeddings `.npy` alignés après ajout incrémental.
- [ ] Row invalide (tag hors set canonique, id non snake_case ASCII D12) rejetée.
- [ ] Signature manquante/invalide → rejet ; anonymisation = placeholders typés.
- [ ] Ré-ingestion idempotente.

Réf : technical-plan T05-T10, data-format, axes-and-tags.
```

---

## 5. Boucle de feedback

**Title :** `[TEST] Boucle de feedback — signaux, trust, online learning, profil, guardrails`

**Body :**

```md
Parent : EPIC

## Objectif
Vérifier la boucle d'apprentissage continu (D08) sous flux de signaux + tenue des garde-fous.

## Surface
- `muses/feedback/{events,trust,instance_reputation,online_learning,style_profile,guardrails,snapshots,meta_suggestions}.py`

## À vérifier
- [ ] 5 signaux distincts captés ; `reject_challenge_appreciated` ≠ `reject_off` (D10).
- [ ] Trust Beta : `95% sur 1000` > `95% sur 5` ; décroissance temporelle.
- [ ] Online learning fait bouger le ranking dans le bon sens sans diverger.
- [ ] Profil : décroissance temporelle ; mode challenge applique un malus profil (T33).
- [ ] Guardrails : sleeper / takeover gated.
- [ ] Snapshots : rollback des poids ML restaure un état antérieur (T40).

Réf : learning-and-trust, style-coaching, D08-D11.
```

---

## 6. API & Auth

**Title :** `[TEST] API & Auth ActivityPub — endpoints, signature stricte, bornes`

**Body :**

```md
Parent : EPIC

## Objectif
Valider la surface HTTP réelle + auth par signature (pas de clé API en clair).

## Surface
- `muses/api/server.py` : `POST /v1/suggest/{dialogue,action,description,thought,video_prompt}`,
  `POST /v1/feedback/signal`, `POST /v1/analyze/{consistency_scene,consistency_session,summary,federated_links}`, `GET /v1/health`
- `muses/api/{auth,signature}.py`
- `muses/api/admin.py` : `GET /v1/admin/coverage` (T35)

## À vérifier
- [ ] Requête non signée / signature invalide → 401/403, jamais traitée.
- [ ] Chaque endpoint renvoie son `response_model` ; payload malformé → 4xx clair.
- [ ] `/v1/admin/coverage` exige le token admin.
- [ ] Bornes (`n`, longueurs, axes inconnus) → pas de 500.
- [ ] `video_prompt` : pipeline sans étage 4 (T44).

Réf : technical-plan T21-T22/T35, use-cases.
```

---

## 7. Client dégradé & analyse

**Title :** `[TEST] Client dégradé & features d'analyse`

**Body :**

```md
Parent : EPIC

## Objectif
Valider résilience client (SPOF assumé, D15) + features d'analyse.

## Surface
- `muses/client.py` (+ `test_client_degraded.py`)
- `muses/analysis/{coherence,matcher,summary,federated_links}.py`

## À vérifier
- [ ] Mode dégradé : service down → client signale proprement (UI grisée, T38), pas de réponse inventée.
- [ ] Timeouts / erreurs réseau gérés.
- [ ] `consistency_scene/session` : incohérence connue remontée, pas de faux positif majeur.
- [ ] `summary` : résumé non vide et traçable.
- [ ] `federated_links` : liens pertinents sur cas témoin, vides sinon.

Réf : technical-plan T24/T38/T45-T50, D15.
```
