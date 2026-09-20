#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
.venv/bin/dramatiq automation.jobs.worker --processes 1 --threads 1
