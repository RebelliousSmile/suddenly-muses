# Contrat de couture `/narrate` (CN → Hub)

Ce dossier contient le contrat **importé de CN** (cn-core), pas défini par le Hub.

| Fichier           | Rôle                                                                 |
| ----------------- | -------------------------------------------------------------------- |
| `schema.json`     | Schéma JSON du corps `POST /narrate`, recopié **verbatim** depuis CN. |
| `PROVENANCE.json` | Reçu de provenance : de quel commit CN provient `schema.json`.       |

## Invariant #4 — le Hub ne hand-type jamais le schéma

`schema.json` est **généré par CN** (`packet.rs` → `generated/schema.json`) et
recopié tel quel. Toute dérive de couture se corrige **dans CN d'abord**, puis se
répercute ici par un réimport. On ne retouche jamais `schema.json` à la main.

## Reçu de provenance (Hub-B)

`PROVENANCE.json` rend la synchronisation **vérifiable**. Champs :

| Champ                | Sens                                                          |
| -------------------- | ------------------------------------------------------------- |
| `source_repo`        | Remote `origin` du checkout CN utilisé pour l'import.         |
| `source_path`        | Chemin du schéma généré dans le dépôt CN.                     |
| `source_commit`      | SHA du commit CN d'où provient le schéma.                     |
| `source_commit_date` | Date de ce commit (ISO 8601).                                 |
| `imported_at`        | Date de l'import côté Hub.                                    |
| `schema_sha256`      | Hash du `schema.json` importé — garde-fou anti-dérive.        |
| `backfill_required`  | `true` tant que le SHA CN n'a pas été capturé (schéma hérité).|

> **État courant.** Le `schema.json` présent a été importé en PR #83 **sans**
> reçu (c'est la dette que Hub-B corrige). `source_commit` vaut donc `unknown` et
> `backfill_required` est `true`. Le prochain import scripté (ci-dessous)
> renseigne le vrai SHA et bascule le flag à `false`.

## Procédure d'import (scriptée)

Depuis un checkout local de CN, à la racine du dépôt Hub :

```bash
scripts/import_narrate_contract.sh <chemin-checkout-CN> [chemin-source-dans-CN]
# ex.
scripts/import_narrate_contract.sh ../cn-core
```

Le script, en un seul mouvement :

1. refuse d'importer si le fichier source est modifié/non committé côté CN
   (sinon le reçu ne résoudrait vers aucun commit réel) ;
2. recopie `schema.json` **verbatim** ;
3. régénère `PROVENANCE.json` (SHA CN, date de commit, remote, hash du schéma).

Schéma et reçu ne peuvent donc pas dériver. Après import, valider la couture :

```bash
pytest tests/muses/narrate/test_provenance.py tests/muses/narrate/test_contract.py
```

`test_provenance.py` échoue si `schema.json` est édité sans repasser par le
script (le hash enregistré ne correspond plus).
