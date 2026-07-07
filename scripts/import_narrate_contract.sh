#!/usr/bin/env bash
#
# Hub-B — Import scripté du contrat /narrate depuis CN (cn-core), avec reçu de
# provenance généré automatiquement.
#
# Invariant #4 : le Hub ne hand-type JAMAIS le schéma. Ce script recopie
# `schema.json` VERBATIM depuis un checkout CN et écrit `PROVENANCE.json` dans le
# même mouvement, de sorte que le reçu résout toujours vers un commit CN réel et
# que schéma ↔ reçu ne peuvent pas dériver.
#
# Usage :
#   scripts/import_narrate_contract.sh <chemin-checkout-CN> [chemin-source-dans-CN]
#
# Exemple :
#   scripts/import_narrate_contract.sh ../cn-core
#   scripts/import_narrate_contract.sh ~/src/cn-core src/scripts/narrative/generated/schema.json
#
set -euo pipefail

CN_DIR="${1:?usage: import_narrate_contract.sh <chemin-checkout-CN> [chemin-source]}"
SRC_REL="${2:-src/scripts/narrative/generated/schema.json}"

# Racine du dépôt Hub (le dossier parent de scripts/).
HUB_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$HUB_ROOT/muses/narrate/contract/schema.json"
RECEIPT="$HUB_ROOT/muses/narrate/contract/PROVENANCE.json"

SRC_ABS="$CN_DIR/$SRC_REL"

# --- Vérifications ---------------------------------------------------------
if [ ! -d "$CN_DIR/.git" ]; then
  echo "✗ '$CN_DIR' n'est pas un checkout git de CN." >&2
  exit 1
fi
if [ ! -f "$SRC_ABS" ]; then
  echo "✗ Source introuvable : $SRC_ABS" >&2
  echo "  (préciser le chemin source en 2e argument si besoin)" >&2
  exit 1
fi

# Le reçu ne vaut que si le fichier source correspond exactement au commit HEAD.
# On refuse d'importer depuis un arbre CN sale sur le fichier de contrat.
if ! git -C "$CN_DIR" diff --quiet -- "$SRC_REL" \
   || ! git -C "$CN_DIR" diff --cached --quiet -- "$SRC_REL"; then
  echo "✗ '$SRC_REL' a des modifications non committées dans le checkout CN." >&2
  echo "  Le reçu de provenance ne pourrait pas résoudre vers un commit réel. Committer côté CN d'abord." >&2
  exit 1
fi

SOURCE_COMMIT="$(git -C "$CN_DIR" rev-parse HEAD)"
SOURCE_COMMIT_DATE="$(git -C "$CN_DIR" show -s --format=%cI HEAD)"
SOURCE_REPO="$(git -C "$CN_DIR" remote get-url origin 2>/dev/null || echo 'local')"
IMPORTED_AT="$(date -u +%Y-%m-%dT%H:%M:%S+00:00)"

# --- Import verbatim + reçu (atomique via python pour l'échappement JSON) ---
cp "$SRC_ABS" "$DEST"

SCHEMA_SHA256="$(python3 -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$DEST")"

python3 - "$RECEIPT" <<PY
import json, sys
receipt = {
    "receipt_version": 1,
    "description": "Reçu de provenance du contrat /narrate importé de CN (cn-core). GÉNÉRÉ — ne pas éditer à la main : régénérer via scripts/import_narrate_contract.sh. Voir contract/README.md.",
    "artifact": "schema.json",
    "source_repo": "$SOURCE_REPO",
    "source_path": "$SRC_REL",
    "source_commit": "$SOURCE_COMMIT",
    "source_commit_date": "$SOURCE_COMMIT_DATE",
    "imported_at": "$IMPORTED_AT",
    "schema_sha256": "$SCHEMA_SHA256",
    "backfill_required": False,
    "note": "Généré au moment de l'import. schema.json est bit-identique au fichier source du commit CN ci-dessus.",
}
with open(sys.argv[1], "w", encoding="utf-8") as fh:
    json.dump(receipt, fh, ensure_ascii=False, indent=2)
    fh.write("\n")
PY

echo "✓ Contrat importé depuis CN @ ${SOURCE_COMMIT:0:12} ($SOURCE_COMMIT_DATE)"
echo "  schema.json  sha256=$SCHEMA_SHA256"
echo "  reçu         $RECEIPT"
echo
echo "Prochaine étape : lancer les tests de couture —"
echo "  pytest tests/muses/narrate/test_provenance.py tests/muses/narrate/test_contract.py"
