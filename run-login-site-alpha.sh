#!/usr/bin/env bash
set -euo pipefail

HEADLESS=false SLOW_MO_MS=300 python3 runner.py --test-login --site site_alpha
