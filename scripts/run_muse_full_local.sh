#!/usr/bin/env bash
# Launch a full-config local Muses instance for ML-quality testing.
#
# Defaults are chosen for a developer workstation:
#   - tables: tables/bootstrap_cell_medfan_combat_hostile_solennel_colere
#   - encoder: sentence_transformer
#   - signature mode: stub
#   - bind host: 127.0.0.1
#   - bind port: 8001
#
# The script fails fast if the target tables directory is missing or empty.
# For a fresh corpus bootstrap, run:
#   PYTHONPATH=. python scripts/bootstrap_initial_cell.py

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

usage() {
  cat <<'EOF'
Usage: scripts/run_muse_full_local.sh [--help]

Launch a local Muses API with the full ML configuration used by phase 5.

Environment overrides (optional):
  MUSES_TABLE_DIR
  MUSES_FEEDBACK_DIR
  MUSES_SNAPSHOT_DIR
  MUSES_BIND_HOST
  MUSES_BIND_PORT
  MUSES_SIGNATURE_MODE
  MUSES_ENCODER
  MUSES_ENCODER_MODEL
  MUSES_LOG_FORMAT
  MUSES_LOG_LEVEL
EOF
}

case "${1:-}" in
  -h|--help)
    usage
    exit 0
    ;;
esac

: "${MUSES_TABLE_DIR:=tables/bootstrap_cell_medfan_combat_hostile_solennel_colere}"
: "${MUSES_FEEDBACK_DIR:=.muses/feedback}"
: "${MUSES_SNAPSHOT_DIR:=.muses/snapshots}"
: "${MUSES_BIND_HOST:=127.0.0.1}"
: "${MUSES_BIND_PORT:=8001}"
: "${MUSES_SIGNATURE_MODE:=stub}"
: "${MUSES_ENCODER:=sentence_transformer}"
: "${MUSES_LOG_FORMAT:=json}"
: "${MUSES_LOG_LEVEL:=INFO}"
: "${MUSES_SIGNATURE_MAX_AGE_SECONDS:=300}"
: "${MUSES_RATE_LIMIT_PER_MINUTE:=60}"

if [[ ! -d "$MUSES_TABLE_DIR" ]]; then
  echo "error: MUSES_TABLE_DIR does not exist: $MUSES_TABLE_DIR" >&2
  echo "hint: bootstrap the corpus first with: PYTHONPATH=. python scripts/bootstrap_initial_cell.py" >&2
  exit 1
fi

shopt -s nullglob
jsonl_files=("$MUSES_TABLE_DIR"/*.jsonl)
shopt -u nullglob
if (( ${#jsonl_files[@]} == 0 )); then
  echo "error: no .jsonl tables found under $MUSES_TABLE_DIR" >&2
  echo "hint: bootstrap the corpus first with: PYTHONPATH=. python scripts/bootstrap_initial_cell.py" >&2
  exit 1
fi

mkdir -p "$MUSES_FEEDBACK_DIR" "$MUSES_SNAPSHOT_DIR"

export MUSES_TABLE_DIR MUSES_FEEDBACK_DIR MUSES_SNAPSHOT_DIR
export MUSES_BIND_HOST MUSES_BIND_PORT MUSES_SIGNATURE_MODE MUSES_ENCODER
export MUSES_ENCODER_MODEL MUSES_LOG_FORMAT MUSES_LOG_LEVEL
export MUSES_SIGNATURE_MAX_AGE_SECONDS MUSES_RATE_LIMIT_PER_MINUTE

missing_embeddings=()
for jsonl in "$MUSES_TABLE_DIR"/*.jsonl; do
  [[ -e "$jsonl" ]] || break
  npy="${jsonl%.jsonl}.embeddings.npy"
  if [[ ! -f "$npy" ]]; then
    missing_embeddings+=("$jsonl")
  fi
done

if (( ${#missing_embeddings[@]} > 0 )); then
  echo "Rebuilding missing embeddings caches for ${#missing_embeddings[@]} table(s)..."
  python - <<'PY'
import os
from pathlib import Path

from muses.tables.embeddings import SentenceTransformerEncoder, rebuild_for_table

repo_table_dir = Path(os.environ["MUSES_TABLE_DIR"])
model_name = os.environ.get("MUSES_ENCODER_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")
encoder = SentenceTransformerEncoder(model_name=model_name)

jsonl_paths = sorted(repo_table_dir.glob("*.jsonl"))
missing = [p for p in jsonl_paths if not p.with_suffix(".embeddings.npy").exists()]
if not missing:
    print("No missing embeddings caches detected.")
    raise SystemExit(0)

for jsonl_path in missing:
    npy_path = jsonl_path.with_suffix(".embeddings.npy")
    count = rebuild_for_table(jsonl_path, npy_path, encoder)
    print(f"  built {npy_path.name} from {jsonl_path.name} ({count} rows)")
PY
fi

cat <<EOF
Launching Muses locally with:
  table_dir    = $MUSES_TABLE_DIR
  feedback_dir = $MUSES_FEEDBACK_DIR
  snapshot_dir = $MUSES_SNAPSHOT_DIR
  bind         = $MUSES_BIND_HOST:$MUSES_BIND_PORT
  encoder      = $MUSES_ENCODER${MUSES_ENCODER_MODEL:+ ($MUSES_ENCODER_MODEL)}
  signature    = $MUSES_SIGNATURE_MODE
  log_format   = $MUSES_LOG_FORMAT
EOF

echo "Use: curl http://$MUSES_BIND_HOST:$MUSES_BIND_PORT/v1/health"

exec python -m uvicorn muses.api.entrypoint:app \
  --host "$MUSES_BIND_HOST" \
  --port "$MUSES_BIND_PORT"
