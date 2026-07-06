"""H3 — Portefeuille Muse pour le métrage du relais `/narrate`.

Modèle minimal : un solde entier par `wallet_key` (`iss/sub`, cf. `session.py`).
Le débit a lieu **après** une génération réussie ; aucune unité n'est débitée
sur erreur provider (cohérent avec `MusesUnavailable`, `muses/client.py`).

H5 (#89, D-89.2) — le `default_grant` de démarrage pour une clé inconnue
n'est PAS un détail dev : c'est le seul levier qui distingue « accès réel
provisionné » de « n'importe quel token validement signé vaut de l'argent ».
`muses/config.py:_resolve_narrate_default_grant` en fait un défaut dépendant
du mode (`0` en `strict`, `1000` en `off`/`stub`) ; `default_grant=0` suffit
ici pour fermer la faille — `balance()`/`debit()` renvoient alors `0` pour
une clé inconnue, et le contrat `/narrate` (schéma : `n >= 1`) garantit que
`wallet.balance(key) < n` est toujours vrai avant tout crédit implicite, donc
402 avant toute génération. Le provisionnement explicite passe par
`credit()` (utilisable directement, ou via l'endpoint admin optionnel
`POST /v1/admin/narrate/credit`, cf. `muses/api/admin.py`). La vraie économie
(achat d'unités, quotas par instance) reste un sujet produit à part.

SQLite, comme les autres stores du Hub (WAL activé par `create_app`).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


class WalletStore:
    def __init__(self, db_path: Path | str, *, default_grant: int = 1000) -> None:
        self.db_path = Path(db_path)
        self.default_grant = default_grant
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS wallet ("
                "key TEXT PRIMARY KEY, balance INTEGER NOT NULL)"
            )

    def balance(self, key: str) -> int:
        """Solde courant. Une clé inconnue vaut `default_grant` (non persisté)."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT balance FROM wallet WHERE key = ?", (key,)
            ).fetchone()
        return int(row[0]) if row is not None else self.default_grant

    def debit(self, key: str, amount: int) -> int:
        """Débite `amount` (jamais sous 0). Initialise au `default_grant` si inconnu.

        Renvoie le nouveau solde.
        """
        if amount < 0:
            raise ValueError("amount must be >= 0")
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT balance FROM wallet WHERE key = ?", (key,)
            ).fetchone()
            current = int(row[0]) if row is not None else self.default_grant
            new_balance = max(0, current - amount)
            conn.execute(
                "INSERT INTO wallet (key, balance) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET balance = excluded.balance",
                (key, new_balance),
            )
        return new_balance

    def credit(self, key: str, amount: int) -> int:
        """Crédite `amount` (recharge / remboursement). Renvoie le nouveau solde."""
        if amount < 0:
            raise ValueError("amount must be >= 0")
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT balance FROM wallet WHERE key = ?", (key,)
            ).fetchone()
            current = int(row[0]) if row is not None else self.default_grant
            new_balance = current + amount
            conn.execute(
                "INSERT INTO wallet (key, balance) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET balance = excluded.balance",
                (key, new_balance),
            )
        return new_balance
