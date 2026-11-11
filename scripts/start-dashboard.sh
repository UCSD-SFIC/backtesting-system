#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

if ! command -v npm >/dev/null 2>&1; then
  echo "Node.js and npm are required to build the dashboard." >&2
  exit 1
fi

if [ ! -d frontend/node_modules ]; then
  npm ci --prefix frontend
fi
npm run build --prefix frontend

if [ ! -x .venv/bin/python ]; then
  echo "Install Python dependencies first: python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt" >&2
  exit 1
fi

exec .venv/bin/python -m uvicorn web.app:app --host 127.0.0.1 --port 8000
