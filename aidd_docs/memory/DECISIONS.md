---
name: decisions
description: Décisions architecturales et produit actées lors du pivot
---

# Décisions

Décisions structurantes prises lors du pivot LoRA → tables+ML (mai 2026). Chaque entrée : ce qui a été décidé, pourquoi, ce qui a été écarté, où c'est documenté en détail.

## D01. Abandon de l'approche LoRA / fine-tune

- **Décidé** : abandonner LoRA stacking, fine-tune sur Qwen2.5-7B/13B, et toute inférence LLM générative en production.
- **Raisons** : volume de corpus insuffisant (jamais 500 sessions/genre atteintes) ; dépendance GPU non tenable pour un service mutualisé gratuit ; mismatch entre le modèle d'apport continu user (row par row) et l'exigence batch du fine-tune.
- **Écarté** : continuer à attendre le corpus dans l'espoir d'atteindre le seuil ; basculer sur un modèle plus petit (gain qualité douteux, problème GPU inchangé) ; abandonner le projet.
- **Conséquence** : pivot complet vers tables + ML léger. Suppression de la stack gateway Railway, RunPod GPU, Cloudflare R2, Together.ai, Fireworks.ai.
- **Cf.** `architecture-tables-ml.md` § Contexte du pivot ; `philosophy.md` §3 ; `LESSONS.md` L05 (mismatch granularité user vs batch).

## D02. Architecture tables curées + ML léger

- **Décidé** : composer les sorties par tirages dans des tables curées, pondérées par un pipeline ML léger CPU-only.
- **Raisons** : la curation explicite garantit la qualité au volume disponible ; le ML léger reste tractable sans GPU ; le résultat est traçable jusqu'à la row tirée.
- **Écarté** : templating pur déterministe (pas d'adaptation contextuelle), retrieval-augmented LLM hosté côté Muses (réintroduit la dépendance GPU et la génération autoregressive), Markov chains pures sur le corpus (pas de pondération contextuelle).
- **Cf.** `architecture-tables-ml.md` § Principes directeurs.

## D03. Pipeline à 4 étages

- **Décidé** : sélecteur → pondérateur → recombinateur → filtreur, chacun avec un rôle distinct.
- **Raisons** : sépare les préoccupations (filtrer les tables, pondérer les lignes, assembler, ranker) ; chaque étage évolue indépendamment ; observabilité par étape.
- **Écarté** : pipeline à 2 étages monolithique (perte d'observabilité), pipeline à 6+ étages (overkill pour le MVP).
- **Cf.** `architecture-tables-ml.md` § Pipeline de génération — 4 étages.

## D04. Étage 3 strictement sans modèle

- **Décidé** : l'étage recombinateur n'utilise aucun modèle ML — règles d'assemblage déterministes + remplissage de slots typés, variantes d'accord pré-stockées comme rows distinctes.
- **Raisons** : c'est ce qui rend tenable la promesse « zéro génération autoregressive » de `philosophy.md` §7. Toute dérive vers de la glue générative ouvrirait la porte à la dépendance LLM et à la perte de traçabilité.
- **Écarté** : petit modèle séquentiel (LSTM, mini-transformer) pour le sequencing ; petite glue génératrice pour les transitions.
- **Si un cas d'usage requiert un assemblage non couvert** : ajouter des rows aux tables, pas introduire un modèle.
- **Cf.** `architecture-tables-ml.md` § Étage 3.

## D05. Cinq axes contextuels canoniques atomiques

- **Décidé** : `univers`, `situation`, `rapport_initial`, `voix`, `emotion_dominante` — cinq axes indépendants, valeurs atomiques.
- **Raisons** : `rapport_initial` (hostile/neutre/amical) change radicalement le ton d'une même situation (combat hostile vs combat amical) ; `emotion_dominante` détermine le lexique activé ; uniformité de schéma quand tous les axes sont atomiques (trust, profil, pondération indexent tous sur `(axe, valeur)`).
- **Écarté** : 3 axes (le triplet initial univers/situation/voix qui occultait rapport et émotion) ; 3 axes avec tuples (situation = (type, rapport), voix = (style, emotion) — non-uniforme dans les schémas) ; tags libres non canonisés (rend l'apprentissage instable).
- **Cf.** `philosophy.md` § Conventions ; `external/axes-and-tags.md` ; `LESSONS.md` L02 (insuffisance des 3 axes initiaux).

## D06. Ekman 6 pour `emotion_dominante`

- **Décidé** : taxonomie Ekman 6 — `colere`, `degout`, `peur`, `joie`, `tristesse`, `surprise`.
- **Raisons** : simplicité d'annotation, ancrage scientifique reconnu, stabilité des traductions inter-langues, base la plus partagée dans la littérature NLP d'analyse d'émotion.
- **Écarté** : Plutchik 8 (plus nuancé mais annotation plus difficile), set custom RP (à inventer, surface d'adoption nulle).
- **Évolution future possible** : extension vers Plutchik 8 si les données montrent un besoin de granularité — pas avant.
- **Cf.** `external/axes-and-tags.md` §5.

## D07. Service unique mutualisé

- **Décidé** : un service Muses unique pour toutes les instances Suddenly du Fediverse, plutôt qu'un service déployé sur chaque instance.
- **Raisons** : apprentissages partagés entre instances (une bonne contribution d'une instance bénéficie aux auteurs d'une autre) ; modération commune ; une seule source de vérité pour le trust.
- **Écarté** : déploiement par instance (perd les apprentissages partagés, multiplie les coûts d'hébergement).
- **Conséquence** : SPOF assumé pour le MVP ; résilience (HA, réplication) reportée dans `infrastructure.md`.
- **Cf.** `philosophy.md` §2.

## D08. Régime continu, pas batch

- **Décidé** : les tables grandissent row par row, les composants ML sont mis à jour incrémentalement à chaque signal — pas de re-training planifié, pas de versions de modèle.
- **Raisons** : aligné avec le modèle d'apport user (chaque interaction génère un signal) ; pas de fenêtre minimale à atteindre ; pas de discontinuité produit.
- **Écarté** : cycles batch périodiques (incompatible avec la modélisation des contributions user comme stream).
- **Cf.** `philosophy.md` §3 ; `learning-and-trust.md` §1 et §3.

## D09. Trust contextuel via Beta reputation par axe

- **Décidé** : chaque user porte un vecteur `trust[axis][value] = (α, β, last_update)` indexé sur les 5 axes canoniques.
- **Raisons** : la distribution Beta distingue naturellement `95% sur 1000 contribs` (haute confiance) de `95% sur 5 contribs` (faible) ; supporte la décroissance temporelle ; tractable à stocker (deux floats par cellule) ; littérature P2P éprouvée (Jøsang).
- **Écarté** : trust scalaire global (perd la dimension contextuelle), moyenne mobile simple (perd la confiance), EigenTrust avec propagation (over-engineering pour un service mutualisé unique).
- **Cf.** `learning-and-trust.md` §4 ; `LESSONS.md` L06 (supériorité de Beta sur moyenne mobile).

## D10. Cinq signaux UI, pas deux

- **Décidé** : l'UI expose `accept`, `accept_edited`, `reject_off`, `reject_challenge_appreciated`, `ignore` — pas juste accept/reject.
- **Raisons** : sans `reject_challenge_appreciated` (« bonne idée, pas pour cette scène »), le ranker apprend à éviter les challenges (taux d'accept plus bas) et le mode challenge collapse mathématiquement en quelques semaines.
- **Écarté** : 2 signaux (accept/reject) ; 3 signaux (accept/edit/reject) sans la distinction d'appréciation du challenge.
- **Conséquence côté instance Suddenly** : deux boutons de rejet visibles dans l'UI, pas un seul.
- **Cf.** `style-coaching.md` §3 ; `LESSONS.md` L03 (mécanique du collapse en mode confort).

## D11. Modes confort et challenge dual constitutifs

- **Décidé** : Muses opère en mode confort (suggestions alignées au style auteur) ou en mode challenge (suggestions volontairement hors zone) ; les deux modes sont constitutifs du produit, pas optionnels.
- **Raisons** : sans le mode challenge, la boucle de feedback converge vers le confort de l'auteur et le système amplifie ses habitudes au lieu de l'aider à évoluer. C'est mécanique.
- **Écarté** : mode confort seul (amplificateur d'habitudes), mode challenge seul (frustrant), mode unique adaptatif.
- **Cf.** `philosophy.md` §1 ; `style-coaching.md` §2.

## D12. Identifiants ASCII snake_case sans accent

- **Décidé** : tous les identifiants (axes, valeurs, niveaux, signaux, types) sont en ASCII snake_case sans accent. Les libellés affichables peuvent porter des accents et de la ponctuation.
- **Raisons** : cohérence de stockage et de query ; portabilité ; sérialisation triviale ; évite les surprises avec normalisation Unicode.
- **Écarté** : libellés français avec accents comme identifiants (`emotion_dominante` ≠ `émotion_dominante`), kebab-case (incohérent avec l'usage Python).
- **Conséquence** : `medieval_fantastique` pas `medieval-fantastique`, `pov_player` pas `pov-player`, etc.
- **Cf.** `external/axes-and-tags.md` § Principes.

## D13. MVP cible — `suggestion de dialogue` (#77)

- **Décidé** : valider le pipeline end-to-end en premier sur la feature `suggestion de dialogue` (#77).
- **Raisons** : c'est la feature avec le pipeline le plus simple — fragments + entités dominants, pas de recombinaison complexe à l'étage 3 (les fragments peuvent être servis quasi tels quels), permet de mesurer la qualité dès quelques centaines de rows dans une cellule contextuelle.
- **Écarté** : commencer par `description` (#79) ou `action` (#78) — pipelines plus dépendants du recombinateur.
- **Cf.** `technical-plan.md` § Choix MVP.

## D14. Conservation de `traductions.md` lors de la purge externe

- **Décidé** : garder `external/traductions.md` malgré son origine LoRA-era.
- **Raisons** : la méthodologie de traduction de gros volumes a une valeur indépendante du pipeline LoRA originel, potentiellement réutilisable pour un futur tagging multilingue ou la traduction de corpus.
- **Cf.** : commit de purge de la mémoire externe (`8b41c80`) qui conserve explicitement ce fichier alors que onze autres LoRA-era sont supprimés. Décision tracée dans le diff du commit lui-même.

## D17. Suddenly AI Hub — validation schéma packet côté CN uniquement

- **Décidé** : le Hub ne valide pas le schéma du `NarrateRequest`. Seul choix-narratifs valide le packet contre le schéma généré depuis `packet.rs`, avant d'envoyer au Hub. Le Hub vérifie uniquement : JSON valide, bornes sur `n`, présence du token.
- **Raisons** : si le Hub valide le schéma, il doit connaître le canon → couplage avec choix-narratifs → effondrement de la frontière fine. C'est la "tentation à fuir" explicitement nommée dans le plan d'action. La cécité au canon est un invariant, pas une convention.
- **Écarté** : paquet versionné `@suddenly/packet-schema` consommé par le Hub (introduit un lien de build entre deux services) ; artefact R2 téléchargé au boot (même problème de couplage, désync runtime en prime).
- **Cf.** `c01127ae-planactionsuddenlyaihub.md` §1 ("Aveugle au canon. Le schéma EST le mur. Tentation à fuir : générer côté serveur") ; brainstorm session 2026-06-03.

## D18. Suddenly AI Hub — auth token JWT signé par Muse

- **Décidé** : Muse émet un JWT (`sub` = user_id, `iss` = muse.domain, durée courte). Le Hub vérifie via le JWK endpoint de l'instance Muse émettrice. Stateless côté Hub.
- **Raisons** : adapté au contexte fédéré multi-instances (chaque instance Muse a son propre `iss` et JWK) ; pas d'état côté Hub ; révocable par rotation de clé ; contrat explicite (champ `iss` + JWK endpoint = interface versionnée).
- **Écarté** : token opaque + introspection (couplage synchrone Hub ↔ Muse sur chaque requête) ; passeport one-time (charge sur Muse à chaque appel `/narrate`) ; token opaque + cache (fenêtre de validité post-révocation).
- **Conséquence** : le Hub doit résoudre le JWK endpoint depuis `iss` (convention `.well-known/jwks.json`). À documenter dans `infrastructure.md` quand il sera rédigé.
- **Cf.** brainstorm session 2026-06-03.

## D16. Suddenly AI Hub — runtime Worker jetable puis Railway

- **Décidé** : Phase 1 = stub HTTP local (pas de déploiement), Phase 2 = Railway directement (même runtime que Hermes).
- **Raisons** : le stub local débloque l'intégration côté choix-narratifs sans aucune décision d'infra ; passer directement à Railway en Phase 2 évite une migration edge→container (Cloudflare Workers → Railway) qui masquerait des différences de comportement sur les appels sortants lourds (Anthropic/OpenRouter).
- **Écarté** : Cloudflare Workers pour le Worker jetable (runtime différent, limites CPU par requête, pas de Postgres natif, double migration vers Railway inévitable) ; Railway dès la Phase 1 (sur-ingénierie avant validation du contrat d'API).
- **Conséquence** : côté CN, la Phase 1 cible une URL localhost configurable ; la bascule Phase 2 est un changement de variable d'environnement, zéro ligne de logique touchée.
- **Cf.** `c01127ae-planactionsuddenlyaihub.md` §3 plan (track Hub), brainstorm session 2026-06-03.

## D15. SPOF du service Muses assumé pour le MVP

- **Décidé** : le service Muses étant unique (D07), c'est un point de défaillance unique pour les features IA de toutes les instances Suddenly. Assumé tel quel jusqu'à la production (M4) — résilience traitée dans `infrastructure.md` après.
- **Raisons** : commencer par un déploiement simple permet d'apprendre sur l'usage réel avant de payer la complexité de la haute disponibilité.
- **Écarté** : HA actif/passif dès le MVP (sur-ingénierie pré-trafic).
- **Cf.** `architecture-tables-ml.md` § Hors périmètre ; `deployment.md`.
