"""H3 — Portefeuille Muse pour le métrage du relais `/narrate`.

Modèle minimal : un solde entier par `wallet_key` (`iss/sub`, cf. `session.py`).
Le débit a lieu **après** une génération réussie ; aucune unité n'est débitée
sur erreur provider (cohérent avec `MusesUnavailable`, `muses/client.py`).

⚠️ Provisionnement / recharge hors périmètre H3 : les clés inconnues reçoivent
un `default_grant` de démarrage. La vraie économie (achat d'unités, quotas par
instance) est un sujet produit à part.

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
