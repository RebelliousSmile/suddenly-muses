---
name: project-brief
description: Vision et domaine du projet Muses
---

# Project brief — Muses

## Vision

**Muses** est une couche d'assistance créative mutualisée entre les instances Suddenly du Fediverse. Une muse au sens classique : elle provoque l'auteur, elle ne le remplace pas.

Identité complète : `philosophy.md`. Architecture : `architecture-tables-ml.md`. Plan d'implémentation : `technical-plan.md`.

## Domaine

- Joueurs de RP de l'écosystème **Suddenly** (Fediverse / ActivityPub) qui écrivent des sessions narratives.
- Le service Muses leur fournit des **suggestions** (dialogue, action, description, pensée intérieure) et des **analyses** (cohérence de scène, de session, résumé, suggestions de liens fédérés, export prompt vidéo) — cf. `external/use-cases.md`.
- Les contributions des joueurs alimentent en retour les tables du service, qui s'enrichissent **row par row** (pas par batches).

## Langage ubiquitaire

| Terme | Définition |
|---|---|
| **Instance** | Serveur Fediverse exécutant Suddenly |
| **Muses (service)** | Le service unique mutualisé décrit par les docs de ce repo |
| **Muses (monnaie)** | Ancienne grille tarifaire, à renommer en « unité d'usage » lors de la refonte |
| **Row** | Une ligne d'une table de Muses, à l'un des quatre niveaux de granularité |
| **Table** | Ensemble de rows au même niveau, partageant un slot d'usage et un tagging axial |
| **Axe canonique** | Un des cinq axes contextuels (`univers`, `situation`, `rapport_initial`, `voix`, `emotion_dominante`) |
| **Étage** | Une des quatre couches du pipeline de génération (sélecteur / pondérateur / recombinateur / filtreur) |
| **Beat narratif** | Unité de niveau scène (hésitation, révélation, rupture de ton…) |
| **Fragment** | Sortie de texte complète prête à insérer |
| **Trust** | Crédit contextuel accordé à un contributeur (Beta reputation par axe) |
| **Carte de couverture** | Hypercube `univers × situation × rapport_initial × voix × emotion_dominante` indexant le peuplement des tables |
| **Mode confort / challenge** | Deux modes de service : conforter le style de l'auteur ou le pousser hors de ses habitudes |
| **Signal UI** | Un des cinq retours utilisateur (`accept`, `accept_edited`, `reject_off`, `reject_challenge_appreciated`, `ignore`) |

## Contraintes structurelles

- **Pas de génération autoregressive.** Les sorties sont composées par sélection et assemblage de lignes pré-écrites. Détail : `philosophy.md` §7 et `architecture-tables-ml.md` § Étage 3.
- **CPU-only en production.** Pas de GPU, pas d'inférence LLM commerciale.
- **Continu, pas batch.** Pas de re-training planifié, pas de versions de modèle. Les tables et les composants ML évoluent ligne par ligne et signal par signal.
- **Service unique mutualisé.** Une seule instance Muses pour toutes les instances Suddenly — SPOF assumé pour le MVP, à traiter dans `infrastructure.md`.
- **Auth ActivityPub.** Toutes les requêtes entrantes sont signées par une instance authentifiée ; pas de clé API en clair.
- **Décentralisation pondérée.** Contributions ouvertes mais filtrées par trust contextuel et réputation d'instance. Détail : `learning-and-trust.md` §§4-6.

## Non-objectifs

- Pas un LLM, pas un chatbot, pas un substitut à l'auteur.
- Pas un assistant généraliste (productivité bureautique, traduction inter-langues, code).
- Pas un service à inférence payante par token.
- Pas un système versionné. Pas de « v2 du modèle ».
- Pas une API OpenAI-compatible. L'ancienne couche réutilisait par convention le chemin `/v1/chat/completions` sans s'engager sur la compatibilité — le nouveau service expose une API REST propriétaire et n'imite plus la surface OpenAI.

Cf. `philosophy.md` §8.

> **Évolution (2026-06-04) — rôle relais `/narrate`.** Depuis l'arrivée de choix-narratifs (CN), le Hub héberge **une seconde famille de routes**, `/narrate` (relais narrateur best-of-N pour CN), qui **appelle un provider LLM**. C'est une exception assumée aux non-objectifs ci-dessus (« pas un LLM », « pas d'inférence payante par token »), **cloisonnée** (D-Hub-0, D16-D18) : elle ne concerne **que** le service CN, jamais le pipeline de suggestion (`/v1/suggest|analyze`), qui reste sans LLM, CPU-only. Le Hub reste aveugle au canon — il ne génère qu'à partir du paquet fourni par CN.

## État du projet

Pré-MVP. Théorie posée dans sept documents (cf. `architecture.md`). Code historique partiellement présent (`pipelines/anonymization`, `pipelines/crawl_rpv`, `apps/playground`) mais hérité de l'ancienne stack LoRA — adaptation et purge à conduire selon `technical-plan.md` M0-M1.

## Sources et liens

- Issues GitHub des features fonctionnelles : [Suddenly #72-#89](https://github.com/RebelliousSmile/suddenly/issues?q=is%3Aissue+label%3Aai)
- Repo : [RebelliousSmile/suddenly-muses](https://github.com/RebelliousSmile/suddenly-muses)
