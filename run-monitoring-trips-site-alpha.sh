#!/usr/bin/env bash
set -euo pipefail

HEADLESS=false SLOW_MO_MS=300 python3 runner.py --test-monitoring-trips --site site_alpha
