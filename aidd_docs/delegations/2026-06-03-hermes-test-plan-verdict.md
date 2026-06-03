---
date: 2026-06-03
agent: hermes
role: agent de test autonome
sujet: verdict plan de test phases 3→7 + redressement
statut: verdict rendu — plan redressé
issues: [75, 76, 77, 78, 79, 80, 81]
---

# Délégation hermes — verdict sur le plan de test et redressement

## Question posée

> hermes a fini la phase 6 du plan de test et posté la review.
> Doit-il faire la phase 7 ? Que doit-il faire ensuite ?

## Ce que hermes a réellement fait

`hermes` a déroulé un « plan de test » structuré en **phases 3→7** (+ sessions 1-2),
chaque phase accompagnée d'un challenge report :

| Plan (tasks)            | Review (reviews)        | Sujet                              | Score |
| ----------------------- | ----------------------- | ---------------------------------- | ----- |
| `phase3_finetuning.md`  | `challenge_phase3.md`   | Fine-tune Qwen2.5 via Axolotl      | 10/10 |
| `phase4_improvement.md` | `challenge_phase4.md`   | Amélioration continue du modèle    | 10/10 |
| `phase5_scaling.md`     | `challenge_phase5.md`   | Scaling corpus / fine-tune         | 9.1   |
| `phase6_production.md`  | `challenge_phase6.md`   | Production HA, vLLM, K8s, API LLM   | 9.1   |
| `phase7_community.md`   | `challenge_phase7.md`   | Open source + communauté           | 9.1   |

## Verdict

**Doit-il faire la phase 7 ? NON.** Et les phases 3-6 sont également hors périmètre.

Raisons (critiques, vérifiées contre le code et la mémoire) :

1. **Architecture morte.** Les phases 3-7 décrivent intégralement la stack
   **LoRA / fine-tune Qwen2.5 / Axolotl / Together.ai / GPU / Kubernetes / vLLM /
   API OpenAI-compatible / open-source community**. Cette stack a été **abandonnée**
   par la décision **D01** (`memory/DECISIONS.md`) lors du pivot LoRA → tables+ML
   (mai 2026). `project_brief.md` liste explicitement en non-objectifs : « Pas un LLM,
   pas un chatbot… Pas une API OpenAI-compatible. »

2. **Critères non testables et faux.** `phase7_community.md` a **tous ses critères
   cochés `[x]`** : « 1000+ stars GitHub », « 500+ membres Discord », « 50+
   contributeurs », « API en production 99.9% uptime ». Ce ne sont ni des faits réels
   (le repo n'a pas ces métriques), ni des comportements d'application qu'un agent de
   test peut exercer — ce sont des objectifs de croissance/marketing.

3. **Reviews = tampons de structure.** Les `challenge_phase*.md` ne vérifient que la
   *forme* du document (« Has Header », « Has Goal », « Has Acceptance Criteria »).
   Aucune ne confronte le plan au code réel ni à l'architecture actuelle. D'où des
   scores 9.1-10/10 sur des plans fantômes.

4. **La vraie application existe déjà.** Le service `muses/` est construit
   (milestones M0-M5, issues GitHub #67-#73 **fermées**) : 44 modules
   (`schemas`, `tables`, `ingestion`, `mining`, `pipeline` 4 étages, `feedback`,
   `api`, `analysis`, `client`) et 37 fichiers de tests unitaires.

## Ce que hermes doit faire ensuite

Tester le **service `muses/` réel**, en validation **comportementale / intégration /
E2E** (les tests unitaires existent déjà — ne pas les réécrire, les exercer et chercher
les défauts réels), contre les contrats réels (`external/use-cases.md`,
`technical-plan.md`, `DECISIONS.md`).

## Issues préparées (backlog de test réel)

- **#75** [EPIC] Plan de test hermes — redressement post-pivot
- **#76** Smoke E2E `suggest_dialogue` de bout en bout (T25)
- **#77** Pipeline 4 étages — contrats & comportement (D03/D04/D11)
- **#78** Ingestion & tables — JSONL / SQLite FTS5 / embeddings (T05-T10)
- **#79** Boucle de feedback — signaux, trust, online learning, profil, guardrails (D08-D11)
- **#80** API & Auth ActivityPub — endpoints, signature stricte, bornes (T21-T22/T35)
- **#81** Client dégradé & features d'analyse (T24/T38/T45-T50, D15)

## Recommandation d'hygiène (non exécutée — à valider)

Archiver ou marquer **OBSOLÈTES** les artefacts LoRA-era pour qu'ils cessent d'induire
en erreur :

- `aidd_docs/tasks/phase{3,4,5,6,7}_*.md`
- `aidd_docs/reviews/challenge_phase{3,4,5,6,7}.md`

Non fait dans cette délégation : suppression/déplacement = décision utilisateur
(ces fichiers peuvent avoir une valeur d'archive historique du pivot).
