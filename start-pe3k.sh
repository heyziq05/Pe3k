#!/usr/bin/env bash
# Pe3k launcher for Linux/macOS. Creates a virtual environment on first run.
# Pe3k by heyziq05 - https://github.com/heyziq05
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  ./.venv/bin/pip install --upgrade pip
  ./.venv/bin/pip install -r requirements.txt
fi
exec ./.venv/bin/python app.py "$@"
