#!/usr/bin/env bash
set -euo pipefail

FLAG="${1:?uso: run-scheduled.sh <flag>}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGS="$ROOT/logs"
LOCKFILE="$LOGS/${FLAG#--}.lock"
LOG="$LOGS/${FLAG#--}.log"

mkdir -p "$LOGS"
exec 9>"$LOCKFILE"
flock -n 9 || { echo "[skip] outra execucao em andamento ($FLAG)" >> "$LOG"; exit 0; }

echo "=== $(date '+%Y-%m-%d %H:%M:%S') $FLAG ===" >> "$LOG"
cd "$ROOT"
.venv/bin/python3 runner.py "$FLAG" >> "$LOG" 2>&1
echo "=== fim $FLAG ===" >> "$LOG"
