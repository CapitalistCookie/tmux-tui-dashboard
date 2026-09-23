#!/usr/bin/env bash
# The whole check: the three panes drawn from the sample feed at 134 columns, the pane checks, the scrub check.
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONDONTWRITEBYTECODE=1
python3 tests/check_panes.py
python3 scrub.py
echo "check: PASS"
