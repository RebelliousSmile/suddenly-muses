# Journal des délégations

Historique des travaux confiés à des agents externes. Une entrée par demande, la plus récente en haut.

---

## 2026-06-03 — Campagne de test E2E du service Muse

- **Agent** : Hermès (CLI conversationnel via passerelle)
- **Plan** : [`2026-06-03-muse-e2e-test-campaign.md`](./2026-06-03-muse-e2e-test-campaign.md)
- **Contexte** : `https://muse.suddenly.social` est déployé et répond, alors que la mémoire projet (D16, `deployment.md`) annonce « pas de déploiement ». L'instance prod tourne en mode dégradé (`tables_count:0`, encodeur stub, `signature_mode:stub`).
- **Missions demandées** :
  - **M1 — Le contrat de l'API tient.** Auth, validation, formes de réponse et sémantique d'erreur conformes sur les endpoints exposés (cible : prod).
  - **M2 — L'écart config déclarée / état réel de la prod est établi.** Comprendre, preuve à l'appui, pourquoi la prod sert un encodeur dégradé et zéro table malgré sa config — avec reco actionnable. (Constat, pas réparation.)
  - **M3 — La qualité ML est prouvée sur une cible correctement configurée.** Pertinence et traçabilité des suggestions, relâchement d'axes, divergence challenge vs confort, effet de la boucle feedback, analyses sémantiques non triviales.
  - **M4 — Un verdict exploitable.** Ce qui marche, ce qui est dégradé, ce qu'il faut corriger — prod vs cible pleine.
- **Statut** : en cours (Hermès a accusé réception et démarré la reconnaissance le 2026-06-03)
- **Verdict** : _à consigner_

---

## 2026-05-15 — Évaluation du stacking LoRA · ⛔ ARCHIVÉ (obsolète)

- **Agent** : Hermès
- **Plan** : [`archive/2026-05-15-stacking-evaluation.md`](./archive/2026-05-15-stacking-evaluation.md)
- **Objet** : pipeline d'évaluation pour une approche LoRA multi-adapters (stacking PEFT, base Qwen2.5-7B, inférence GPU).
- **Statut** : **obsolète, ne pas exécuter.** Archivé le 2026-06-03.
- **Raison** : architecture supprimée par le pivot D14 (tables + ML léger, CPU-only). Aucun fichier visé n'existe plus (`scripts/infer.py`, `scripts/list_models.py`, `models/`, deps `peft`/`torch`). Conservé comme trace historique.
