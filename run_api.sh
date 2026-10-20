#!/usr/bin/env bash
# Start the desk API on a local chain, with the vision-reader keys from .env if present.
cd "$(dirname "$0")"
if [ -f .env ]; then set -a; . ./.env; set +a; fi
NETWORK="${NETWORK:-localhost}" SIGNING="${SIGNING:-client}" exec .venv/bin/uvicorn apagent.api:app --port "${PORT:-8000}"
