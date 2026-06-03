# Délégations

Trace, versionnée, des travaux **confiés à des agents externes** (Hermès, etc.) — ce qui a été demandé, à quel agent, et ce qui en est ressorti.

## Ce que ce dossier est, et n'est pas

- **Est** : la source de vérité, côté repo, des missions déléguées et de leur historique. Distinct de `aidd_docs/tasks/`, qui suit le travail-produit du Hub lui-même.
- **N'est pas** : le répertoire de travail d'un agent. Il n'y a **aucune synchronisation** avec la machine d'un agent. Transférer un plan à Hermès est une **étape d'export manuelle** (copie sur son hôte) — pas un montage partagé. C'est pourquoi on ne reproduit pas ici l'arborescence interne d'un agent (ex. `.hermes/`).

## Contenu

| Fichier | Rôle |
|---|---|
| `journal.md` | Historique daté : ce qui a été demandé · agent · plan lié · verdict |
| `AAAA-MM-JJ-<slug>.md` | Plan de mission délégué (objectifs + critères de réussite). Exporté vers l'agent au moment de l'exécution. |

## Cycle d'une délégation

1. On rédige le plan de mission ici (altitude objectif/critères, pas mécanique).
2. On l'exporte vers l'agent (copie sur son hôte).
3. L'agent exécute et rend compte.
4. On consigne le verdict dans `journal.md` (et, si besoin, un fichier de revue à côté).
