#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

mkdir -p logs

git pull --ff-only --autostash

if [[ ! -x ".venv/bin/python" ]]; then
  echo "Missing .venv/bin/python. Run scripts/install_macos_launchd.sh first."
  exit 1
fi

.venv/bin/python -m src.jobs close-scan

git add stock_strategy.sqlite3

if git diff --cached --quiet -- stock_strategy.sqlite3; then
  echo "stock_strategy.sqlite3 has no changes to commit."
  exit 0
fi

timestamp="$(date '+%Y-%m-%d %H:%M:%S %z')"
git commit -m "Update stock strategy close scan data $timestamp"
git push
