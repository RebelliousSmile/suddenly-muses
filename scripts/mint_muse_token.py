"""H5 (#89, Phase 2) — CLI de référence : émission côté instance (D18).

Rend démontrable, sans dépendance nouvelle, le chemin "un utilisateur réel
obtient un token Muse valide sans connaître le secret du Hub" :

1. Génère une paire de clés RSA (ou en charge une existante via `--key-file`).
2. Émet le document JWKS à publier sur l'instance à
   `https://<iss>/.well-known/jwks.json`.
3. Signe un token de session `{sub, iss, exp}` pour l'utilisateur donné.

Ce script détient la clé privée — il tourne côté instance émettrice, jamais
côté Hub (`muses/api/*`, `muses/narrate/session.py`/`jwks.py`/`wallet.py`).

Usage :
    PYTHONPATH=. python scripts/mint_muse_token.py --sub alice --iss muse.example

    # Persister/réutiliser la même clé entre invocations :
    PYTHONPATH=. python scripts/mint_muse_token.py --sub alice --iss muse.example \\
        --key-file instance_key.pem

    # Écrire JWKS et token dans des fichiers plutôt que stdout :
    PYTHONPATH=. python scripts/mint_muse_token.py --sub alice --iss muse.example \\
        --jwks-out jwks.json --token-out token.txt

Configuration Hub correspondante (`.env`) :
    MUSES_NARRATE_AUTH_MODE=strict
    MUSES_NARRATE_JWKS_ENABLED=true
    MUSES_NARRATE_JWT_ISSUERS=muse.example
    MUSES_NARRATE_JWT_ALGORITHM=RS256
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from muses.narrate.issuer import DEFAULT_TTL_SECONDS, MuseIssuer


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sub", required=True, help="identifiant utilisateur (claim sub)")
    parser.add_argument("--iss", required=True, help="domaine de l'instance émettrice (claim iss)")
    parser.add_argument(
        "--ttl-seconds",
        type=int,
        default=DEFAULT_TTL_SECONDS,
        help=f"durée de vie du token en secondes (défaut: {DEFAULT_TTL_SECONDS})",
    )
    parser.add_argument(
        "--key-file",
        type=Path,
        default=None,
        help="charge une clé privée PEM existante au lieu d'en générer une fraîche",
    )
    parser.add_argument(
        "--jwks-out",
        type=Path,
        default=None,
        help="écrit le document JWKS dans ce fichier (défaut: stdout)",
    )
    parser.add_argument(
        "--token-out",
        type=Path,
        default=None,
        help="écrit le token minté dans ce fichier (défaut: stdout)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.key_file is not None:
        issuer = MuseIssuer.from_pem(args.key_file.read_bytes())
    else:
        issuer = MuseIssuer.generate()

    jwks_document = issuer.jwks_document()
    token = issuer.mint_token(args.sub, args.iss, args.ttl_seconds)

    jwks_text = json.dumps(jwks_document, indent=2)
    if args.jwks_out is not None:
        args.jwks_out.write_text(jwks_text + "\n", encoding="utf-8")
        print(f"JWKS écrit -> {args.jwks_out} (à publier à https://{args.iss}/.well-known/jwks.json)")
    else:
        print(f"# JWKS à publier à https://{args.iss}/.well-known/jwks.json")
        print(jwks_text)

    if args.token_out is not None:
        args.token_out.write_text(token + "\n", encoding="utf-8")
        print(f"Token écrit -> {args.token_out}")
    else:
        print(f"# Token (sub={args.sub!r}, iss={args.iss!r}, kid={issuer.kid!r})")
        print(token)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
