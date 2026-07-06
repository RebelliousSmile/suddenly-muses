---
name: infrastructure
description: Spec opérationnelle de l'infrastructure et de l'API du service Muses
---

# Infrastructure et API opérationnelle

> Projet pré-MVP. Cette spec couvre l'API actuellement implémentée (M0-M3) et fixe les contraintes pour le déploiement public M4. La haute disponibilité au-delà du SPOF assumé (cf. `DECISIONS.md` D15) n'est pas dans le périmètre tant que la charge réelle ne le justifie pas.

## Topologie cible

```
[ Instance Suddenly A ]──┐
[ Instance Suddenly B ]──┼── HTTPS signé ActivityPub ──►  [ Service Muses, single VM CPU ]
[ Instance Suddenly C ]──┘                                   │
                                                             ├── tables/      JSONL versionnés git
                                                             ├── feedback/    SQLite local (trust, profil, learner, instance_rep, event log)
                                                             └── snapshots/   copies horodatées des SQLite (T40)
```

## Endpoints HTTP

| Méthode | Path | Auth | Description | Codes |
|---|---|---|---|---|
| GET | `/v1/health` | aucune | Liveness check. Renvoie `tables_count`, `encoder_dim`, `feedback_enabled` | 200 |
| POST | `/v1/suggest/dialogue` | Signature HTTP | Feature dialogue (#77). Body : `SuggestRequest`. Réponse : `SuggestResponse` avec traçabilité (rows servies + scores + axes relâchés) | 200, 400 (mauvaise feature), 401 (signature manquante/invalide), 422 (tags hors canon) |
| POST | `/v1/feedback/signal` | Signature HTTP | Capture d'un signal UI (5 types). Body : `FeedbackSignalRequest`. Dispatche vers trust + style + learner | 200, 401, 503 (feedback désactivé) |
| GET | `/v1/admin/coverage` | `X-Admin-Token` (optionnel) | Carte de couverture par cellule (counts_by_level, distinct_contributors, last_contribution) | 200, 403 |

Schémas détaillés : `muses/api/schemas.py` et `muses/api/server.py`.

## Authentification ActivityPub (cible M4)

Le MVP M2/M3 utilise `require_signature_stub` qui parse le header `Signature` (RFC draft-cavage) mais ne vérifie pas la signature cryptographique. À implémenter en M4 :

1. **Parsing** : `keyId`, `algorithm`, `headers`, `signature` (déjà fait par `parse_http_signature`).
2. **Résolution de l'acteur** : `keyId` = URI ActivityPub d'un objet `publicKey`. Fetch l'acteur (`GET <actor>` avec `Accept: application/activity+json`) → récupérer `publicKey.publicKeyPem`.
3. **Vérification** :
   - Reconstruire le `signingString` canonical depuis les headers listés (`request-target`, `host`, `date`, `digest`, etc.).
   - Vérifier `signature` avec la clé publique RSA-SHA256.
4. **Validation du `Digest`** si présent : `SHA-256=base64(sha256(body))`.
5. **Anti-replay** : rejeter `date` trop ancienne (>5 min).

Le résultat enrichit `ParsedSignature` avec `actor_uri` validé, utilisé pour peupler `user_id` / `instance_id` dans les signals et les rows.

Implémentation suggérée : librairie `httpsig` ou implémentation maison ~150 lignes.

## Mode dégradé côté client (M4/T38)

`MusesClient.suggest` lève `MusesUnavailable` sur :

- timeout HTTP
- erreurs réseau (DNS, refusal)
- codes 5xx du service

Convention côté instance Suddenly : attraper `MusesUnavailable` → griser le bouton IA + message « Assistant indisponible, réessayez plus tard » (cf. `external/use-cases.md` §4.3). Aucune unité d'usage n'est débitée sur cet échec.

Les 4xx restent propagés via `httpx.HTTPStatusError` — ce sont des erreurs de la requête (signature invalide, tags hors canon), pas du service.

## Stockage opérationnel

| Type | Backend | Schéma source | Backup |
|---|---|---|---|
| Tables (rows) | JSONL versionnés git | `external/data-format.md` | git remote |
| Index FTS5 des rows | SQLite local | `muses/tables/sqlite_index.py` | reconstruit depuis JSONL |
| Embeddings rows | `.npy` adjacent | `muses/tables/embeddings.py` | reconstruit depuis JSONL |
| Trust contributeur | SQLite local | `muses/feedback/trust.py` | snapshots T40 |
| Réputation instance | SQLite local | `muses/feedback/instance_reputation.py` | snapshots T40 |
| Profil de style | SQLite local | `muses/feedback/style_profile.py` | snapshots T40 |
| Online learner | SQLite local | `muses/feedback/online_learning.py` | snapshots T40 |
| Event log signaux | JSONL append-only | `muses/feedback/events.py` | rotation périodique + archivage |

Les SQLite sont reconstructibles depuis l'event log (rejouable). Les snapshots permettent un rollback rapide sans rejouer l'historique complet.

## Snapshots et rollback (M4/T40)

`muses.feedback.snapshots` :

- `snapshot_directory(source_dir, snapshot_dir)` — copie horodatée d'un dossier (typiquement `feedback/`).
- `list_snapshots(snapshot_dir)` — liste antichronologique.
- `restore_snapshot(snapshot_path, target_dir)` — restauration (écrase la cible).

Politique :
- Snapshot automatique toutes les N heures (à figer en production).
- Conservation roulante des K derniers snapshots.
- Snapshot pré-déploiement systématique.

Le rollback **ne supprime pas** les rows JSONL ajoutées après le snapshot — seuls les poids ML / trust / profils sont rétablis.

## Déploiement v0 (M4/T37 — hors session)

Cible : VM unique CPU-only, distribution Linux standard.

Étapes attendues :

1. Provisioner une VM (ex: Hetzner CX22 — 2 vCPU, 8 GB RAM, 50 GB SSD pour ~6€/mois).
2. Cloner le repo, `pip install -e .[api,embeddings,pipelines]`.
3. Configurer un service systemd qui lance `uvicorn muses.api.server:app` (avec `app = create_app(...)` configuré par un module wrapper qui lit les chemins depuis `.env`).
4. Reverse proxy nginx avec TLS Let's Encrypt sur `muses.<domaine>`.
5. Persistance : `tables/`, `feedback/`, `snapshots/` sur un disque dédié.
6. Cron : snapshots horaires + scan anti-sleeper quotidien.
7. Monitoring : Prometheus node_exporter + healthcheck `/v1/health` via Blackbox.

À documenter en script `scripts/deploy/install_v0.sh` quand T37 est exécutée.

## Déploiement Railway

Cible alternative au déploiement bare-metal Hetzner — Railway gère build + run + TLS + scaling à un coût de ~5 USD/mois (Hobby plan), sans bare-metal à provisionner.

La config build/deploy vit dans `railway.toml` à la racine. **Ce fichier prend toujours le dessus sur les réglages dashboard** — c'est la source de vérité versionnée.

### Provisionnement (à faire une fois côté Railway dashboard)

1. **Créer un projet** lié au repo GitHub (`RebelliousSmile/suddenly-muses`).
2. **Provisionner un Volume** d'au moins 1 GB monté sur `/data`. Railway ne permet pas de déclarer les volumes dans `railway.toml`.
3. **Configurer les variables d'environnement** (Variables tab) :

   | Variable | Valeur Railway typique | Notes |
   |---|---|---|
   | `MUSES_TABLE_DIR` | `tables/bootstrap_cell_medfan_combat_hostile_solennel_colere` | In-image (versionné git) |
   | `MUSES_FEEDBACK_DIR` | `/data/feedback` | Volume monté, persistant |
   | `MUSES_SNAPSHOT_DIR` | `/data/snapshots` | Volume monté |
   | `MUSES_ADMIN_TOKEN` | secret fort (`openssl rand -base64 32`) | **Obligatoire** — bind public sinon `ConfigError` |
   | `MUSES_SIGNATURE_MODE` | `strict` | Production = vérification RSA-SHA256 réelle |
   | `MUSES_ENCODER` | `sentence_transformer` | Modèle baké dans l'image au build |
   | `MUSES_ENCODER_MODEL` | `paraphrase-multilingual-MiniLM-L12-v2` | Par défaut |
   | `MUSES_BIND_HOST` | `0.0.0.0` | Railway expose `$PORT` |
   | `MUSES_LOG_FORMAT` | `json` | Logs structurés pour ingestion |
   | `MUSES_LOG_LEVEL` | `INFO` | |
   | `MUSES_RATE_LIMIT_PER_MINUTE` | `60` | Single-worker, ajustable |
   | `MUSES_SIGNATURE_MAX_AGE_SECONDS` | `300` | Anti-replay 5 min |

   Railway fournit `PORT` automatiquement — `startCommand` du `railway.toml` l'utilise.

4. **Public domain** : générer un nom Railway ou attacher un domaine personnalisé (TLS automatique).

5. **Déclencher le premier deploy** depuis le dashboard ou push sur `main`.

### Premier boot

- Le service charge `MUSES_TABLE_DIR` (in-image, versionné). 3 tables peuplées par le bootstrap script committed dans `tables/bootstrap_cell_*/`.
- `MUSES_FEEDBACK_DIR=/data/feedback` est créé automatiquement par les stores au premier signal.
- L'event log + trust + style profile + online learner s'initialisent vides.
- Snapshots déclenchés manuellement via `railway run python scripts/snapshot_feedback.py` ou via cron-style scheduler externe.

### Mise à jour des tables

Les tables sont **in-image** (versionnées git). Toute évolution (curation, mining, nouvelle cellule) demande :
1. Modifier les JSONL dans `tables/...` localement
2. Commit + push sur `main`
3. Railway redéploie automatiquement
4. Les nouvelles tables sont chargées au prochain start

C'est acceptable au volume MVP. À volume élevé, il faudra migrer vers une source externe (S3 / R2 / volume Railway dédié sync via job).

### Limites Railway à acter

- **Free trial** : ~5 USD de crédit puis pause. **Hobby plan** : ~5 USD/mois fixe, suffisant pour le MVP. **Pro plan** ajoute concurrence et SLA.
- **Build time** : ~10 min sur Hobby. Notre build (~3 min Nixpacks + ~2 min bake du modèle) passe largement.
- **RAM** : 512 MB par défaut Hobby — sentence-transformer + Python ≈ 350 MB, marge serrée mais OK.
- **Single replica** : on assume le SPOF (D15). Toute mise à `numReplicas > 1` exige de migrer les stores SQLite vers une DB partagée.
- **Sinistre volume** : si le volume Railway est perdu, on perd `feedback/` entier (trust, profils, event log). Les snapshots restaurent un état antérieur mais doivent eux-mêmes être exfiltrés hors Railway pour vraie résilience. À traiter quand le service quitte le pré-MVP.

### Reproductibilité sur d'autres PaaS

Le `Procfile` n'est pas fourni mais le `startCommand` est trivialement transposable :

- **Fly.io** : `fly.toml` avec `[processes] app = "uvicorn ..."` et un volume monté.
- **Render** : `render.yaml` avec `services` (équivalent direct, mêmes env vars).
- **Heroku-likes** : `Procfile` avec `web: uvicorn muses.api.entrypoint:app --host 0.0.0.0 --port $PORT`.

## Capacity planning indicatif

| Mesure | M2 | M3 | M4 nominal |
|---|---|---|---|
| Tables (KB total) | ~50 | ~50 | 1-100 MB |
| Embeddings (MB) | <1 | <1 | 10-500 |
| Event log (lignes/jour) | 0 | 0-100 | 1k-100k |
| Trust DB (rows) | 0 | 10-100 | 1k-1M |
| Latence p95 suggest | <50ms (StubEncoder) | <50ms | <300ms (sentence-transformer CPU) |
| RAM idle | ~50MB | ~80MB | 500MB-1GB |

## Émission de tokens Muse pour `/narrate` (H5, #89, D18)

Convention `.well-known/jwks.json` : chaque instance émettrice publie ses clés
publiques RSA à `https://<iss>/.well-known/jwks.json`, format JWK standard
(`{"keys": [{"kid", "kty": "RSA", "use": "sig", "alg": "RS256", "n", "e"}]}`).
Le Hub (`muses/narrate/jwks.py`) résout la clé par `iss` puis `kid` — TTL cache,
`iss` en liste blanche vérifiée AVANT tout fetch (garde SSRF), https obligatoire
(sauf `localhost`/`127.0.0.1`). Le Hub ne détient et ne fetch jamais de clé privée.

Flux opérateur (instance émettrice → Hub) :

1. Générer une paire de clés et un token de démo : `python scripts/mint_muse_token.py --sub <user> --iss <domaine-instance>` (`--key-file` pour réutiliser la même clé entre invocations, `--jwks-out`/`--token-out` pour écrire des fichiers).
2. Publier le JWKS imprimé à `https://<domaine-instance>/.well-known/jwks.json` (statique, régénéré à chaque rotation de clé).
3. Distribuer le token minté au client (CN) comme `Authorization: Bearer <token>`.
4. Configurer le Hub : `MUSES_NARRATE_JWKS_ENABLED=true`, `MUSES_NARRATE_JWT_ISSUERS=<domaine-instance>`, `MUSES_NARRATE_JWT_ALGORITHM=RS256`, sans `MUSES_NARRATE_JWT_SECRET`.

La clé privée ne vit que côté instance émettrice (`muses/narrate/issuer.py`, jamais importé par `muses/api/*` ni par le chemin de vérification). Voir `muses/narrate/issuer.py` (`MuseIssuer`) pour l'implémentation de référence.

## Hors périmètre

- **Haute disponibilité** (réplication, failover) — D15 acte le SPOF pour le MVP.
- **Multi-region** — non pertinent au volume cible initial.
- **Authentification admin via ActivityPub** — pour MVP, `X-Admin-Token` statique suffit.
- **Rate limiting public** — à ajouter avant ouverture publique (`slowapi` ou middleware custom).
