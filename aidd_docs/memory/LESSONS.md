---
name: lessons
description: Leçons apprises lors du pivot LoRA → tables+ML
---

# Leçons

Observations méthodologiques et techniques tirées du travail de pivot (mai 2026). Cf. `DECISIONS.md` pour les décisions actées, `lessons_sessions_1-2.md` pour les leçons des sessions pré-pivot.

## L01. Distinguer `world model` (RL) de `online preference learning`

Quand un user décrit l'envie d'« un système qui s'améliore avec l'usage », il faut désambiguïser :

- **World model au sens RL** (Ha & Schmidhuber, DreamerV3) : modèle latent appris de la dynamique d'un environnement, support à la planification par rollouts imaginés. Concept précis, pas applicable à la narration en stack mature.
- **Online preference learning** : boucle de feedback qui met à jour un ranker à partir de signaux user. Largement maîtrisé (RRPO, DPO-lite, Constitutional AI). C'est ce qui répond à « les dialogues s'améliorent avec l'usage ».

Confondre les deux conduit à promettre un objet de recherche (world model narratif) alors qu'on construit un objet d'ingénierie (boucle feedback sur retrieval). La doc doit nommer correctement.

## L02. Trois axes contextuels étaient insuffisants

La canon initiale (`univers`, `situation`, `voix`) loupait deux dimensions qui changent radicalement les sorties :

- `rapport_initial` (hostile / neutre / amical) — un combat amical et un combat hostile partagent `situation: combat` mais n'ont rien à voir.
- `emotion_dominante` — conditionne le lexique activé indépendamment du style narratif.

**Leçon** : les axes dimensionnels qu'on intuite comme « implicites » dans le contexte doivent être promus en axes canoniques **explicites** dès qu'ils déterminent significativement la sortie. Sinon le ML n'a pas le signal pour les traiter.

## L03. Cinq signaux UI au lieu de deux

`accept` / `reject` seuls font collapser le mode challenge en quelques semaines : les challenges ont un taux d'accept structurellement plus bas, donc le ranker apprend à les éviter. C'est mécanique.

**Leçon** : quand un signal a une sémantique ambiguë (un reject = « pas pertinent » OU « bonne idée pas maintenant »), la désambiguïsation doit être un **élément d'UI explicite**, pas un post-traitement statistique. Le `reject_challenge_appreciated` est devenu indispensable.

## L04. L'étage 3 doit rester strictement non-génératif

Toute tentation de mettre « juste un petit modèle » à l'étage 3 (glue génératrice, mini-transformer pour les transitions) casse le contrat « zéro génération autoregressive » de `philosophy.md` §7. Conséquences en cascade : dépendance LLM réintroduite, traçabilité perdue, coût d'inférence redevient linéaire à la longueur.

**Leçon** : quand un contrat structurel est revendiqué dans la philosophie, les étages techniques doivent être conçus pour le rendre tenable **par construction**. Si un cas d'usage exige un assemblage non couvert, on ajoute des rows à la table — pas un modèle.

## L05. Apport continu user et fine-tune batch sont incompatibles

C'est la racine du pivot. Le fine-tune (LoRA ou complet) exige une fenêtre minimale de données pour produire un nouveau modèle, et chaque cycle est discret. L'apport user est continu et granulaire (une row, un accept, une édition).

**Leçon** : avant de choisir une architecture, vérifier que sa **granularité d'update** matche la granularité du flux de données. Un mismatch fondamental impose un pivot, pas juste un ajustement.

## L06. Beta reputation est strictement supérieur à une moyenne mobile

Une moyenne mobile à 95% peut signifier 95% sur 5 contribs (faible confiance) ou 95% sur 1000 (haute). Confondre les deux ouvre la porte aux sleeper attacks et aux raids massifs.

**Leçon** : pour tout score qui sert à pondérer du contenu d'autrui, utiliser une primitive qui sépare **valeur** et **confiance** — typiquement Beta reputation (Jøsang). Coût : deux floats au lieu d'un. Bénéfice : robustesse contre les attaques classiques.

## L07. Cohérence d'identifiants demande grep systématique

Malgré la canonisation explicite (ASCII snake_case sans accent), `medieval-fantastique` et `pov-player` ont continué à leaker dans les exemples des docs. Détectés par grep ciblé en pass de critique, pas à la lecture.

**Leçon** : poser une convention de nommage est nécessaire mais pas suffisant. Il faut **un grep automatisé** des occurrences interdites au moment de chaque revue. Idéalement un check CI le ferait.

## L08. Cohérence cross-doc demande plusieurs passes

Quand le canon évolue (passage de 3 à 5 axes, par exemple), les références dans les autres docs ne suivent pas automatiquement. Plusieurs passes de critique ont été nécessaires pour rattraper les contradictions (références à `genre` au lieu de `univers`, sections renumérotées, etc.).

**Leçon** : à chaque évolution structurante d'un doc canonique, **dérouler immédiatement** la critique pass sur les docs qui le référencent. Plus on attend, plus les contradictions s'accumulent.

## L09. Documenter les anti-features cadre les discussions

`philosophy.md` §8 « Ce que Muses n'est pas » a sauvé plusieurs discussions ambiguës (« pourquoi pas un LLM », « pourquoi pas une API OpenAI-compatible »). Cadrer ce que le projet n'est pas est aussi instructif que le cadrer par ce qu'il est.

**Leçon** : pour un projet exposé à de nombreuses sollicitations d'extension, formaliser les anti-features réduit les débats à chaque demande nouvelle.

## L10. Le rituel `0 deal breakers / 0 suggestions` produit des docs robustes

Plusieurs cycles de critique structurée (« challenge ta rédaction → corrige tout ») ont systématiquement révélé des problèmes invisibles à la première écriture : contradictions cross-doc, références cassées, identifiants inconsistants, formules sans définition.

**Leçon** : faire du rituel de critique un livrable explicite (pas un implicite) permet de tendre vers zéro defect documentaire. Chaque passe découvre des choses que la précédente avait laissé passer — viser zéro en une seule passe n'est pas réaliste, viser zéro après deux ou trois passes l'est.

## L11. Mélanger français et anglais dans le code crée du bruit

Les exemples utilisaient parfois `axe / valeur` (FR) et parfois `axis / value` (EN) pour la même chose. Conséquence : grep manqués, doutes à la lecture.

**Leçon** : trancher tôt sur la langue par registre et s'y tenir. Le canon Muses (cf. `external/axes-and-tags.md`) utilise du français snake_case ASCII pour les valeurs métier (`medieval_fantastique`, `narquois`, `combat`, `colere`…) et de l'anglais pour la terminologie technique d'API et de schéma (`level`, `tags`, `signature`, `suggest`, `analyze`). Le risque attaqué par cette leçon n'est pas le choix lui-même mais le **mélange** dans un même registre — ce qui produit `axe` en français à côté de `axis` en anglais pour désigner la même chose.

## L12. Garder l'historique avec un bandeau d'obsolescence

`issues-analysis.md` était un snapshot pré-pivot ; le supprimer aurait perdu le contexte historique, le garder tel quel aurait induit en erreur. La solution : bandeau d'obsolescence en tête + correction des références les plus cassantes + reste du contenu préservé comme trace.

**Leçon** : pour les snapshots historiques, ni purge ni laisser-faire — un bandeau explicite qui dit « ceci est un instantané daté, voir XYZ pour l'état courant » préserve l'archéologie sans coût pédagogique.

## L13. spaCy : disable= est par modèle, pas partagé

`fr_core_news_md` n'a pas de composant `tagger` — il utilise `morphologizer`. Passer `disable=["tagger", ...]` sur ce modèle lève `ValueError: [E007]` à l'initialisation. Les listes de composants diffèrent entre les modèles FR et EN.

- FR : `disable=["morphologizer", "parser", "attribute_ruler", "lemmatizer"]`
- EN : `disable=["tagger", "parser", "senter", "attribute_ruler", "lemmatizer"]`
- Ne jamais désactiver `tok2vec` — il alimente `ner` en interne.

**Leçon** : toujours définir `disable=` par modèle. Une liste partagée est un crash garanti dès qu'on charge un modèle d'une autre langue.

## L14. Batch NLP : préserver l'ordre du compteur après nlp.pipe()

Quand on batchise plusieurs textes avec `nlp.pipe()` par groupe de langue (FR d'abord, EN ensuite), le compteur `[PER_N]` s'incrémente dans l'ordre de traitement des groupes, pas dans l'ordre d'apparition des messages. Pour une session mixte `[fr, en, fr]`, le batch FR traite les messages 0 et 2 avant le message 1 (EN) — donc PER_2 = premier nom FR du message 2, pas le premier nom EN du message 1.

**Fix** : stocker les docs dans `dict[int, Doc]` keyed par index original, puis itérer `range(len(messages))` pour assigner le compteur — l'ordre des messages d'origine est préservé.

**Leçon** : le batch par groupe de langue est une optimisation d'inférence, pas un changement d'ordre sémantique. Les deux doivent être découplés.

## L15. Ne pas supprimer une fonction testée lors d'une refacto de signature

Quand on refactore la signature d'une fonction (`_replace_persons` : ajout de `doc: Doc | None = None`), les tests qui importent et appellent directement cette fonction continuent d'attendre l'ancienne interface. La supprimer et inliner la logique casse l'import des tests.

**Leçon** : si des tests importent une fonction par nom, la garder avec sa signature étendue (paramètre optionnel). Ne la supprimer que si les tests sont mis à jour dans le même commit.

## L16. L'ordre des gardes dans un validateur fail-fast est significatif

Dans `config._validate()` (plusieurs `if ... raise ConfigError` séquentiels), ajouter une nouvelle garde AVANT une garde existante peut masquer le message d'erreur de cette dernière quand un même scénario de test viole les deux conditions à la fois. Constaté sur #89 : une nouvelle garde `admin_token requis en strict` placée avant la garde `issuers requis si JWKS` a fait échouer `test_strict_narrate_jwks_enabled_without_issuers_refused` (le test ne posait pas `admin_token`, donc la nouvelle garde levait sa propre erreur en premier, avec un message ne correspondant plus au regex attendu par le test).

**Leçon** : en ajoutant une garde à une fonction de validation à guards séquentielles, vérifier quelles gardes existantes partagent une précondition (ici : ni l'une ni l'autre n'était posée par le test visé) et placer la nouvelle garde après elles, ou faire tourner toute la suite de tests concernés avant de considérer l'ajout terminé — pas seulement les tests qu'on pense affectés.
