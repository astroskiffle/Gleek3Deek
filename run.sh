#!/usr/bin/env bash
# Gleek3Deek launcher for macOS / Linux
set -e
cd "$(dirname "$0")"

PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then
    echo "Python 3.9+ not found. Install it from https://www.python.org/downloads/"
    exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
    echo "Creating virtual environment..."
    "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

if [ ! -f ".venv/.gleek_installed" ]; then
    echo "Installing required packages (first run only, this can take a few minutes)..."
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    echo "Installing optional FBX/DAE/LWO support (safe to fail)..."
    python -m pip install assimp-py || echo "assimp-py unavailable for this Python; FBX/DAE/LWO will need the assimp CLI."
    touch .venv/.gleek_installed
fi

exec python main.py "$@"
