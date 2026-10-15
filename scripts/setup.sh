#!/usr/bin/env bash
# MasT setup for Linux (Rocky Linux 10 etc.).
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PYTHON:-python3}
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev,web]"
[ -f config.yaml ] || { cp config.example.yaml config.yaml; echo "Created config.yaml"; }
echo
echo "Done. Activate with:  source .venv/bin/activate"
echo "Then: export ANTHROPIC_API_KEY=sk-...  &&  mast check-llm"
