#!/usr/bin/env bash
# =============================================================================
# Bonded Payables Agent - Local Development & Runner Script
# =============================================================================
# Launches all system services together:
#   1. Local Hardhat Blockchain (port 8545) & deploys contracts
#   2. Better Auth Service (port 3001)
#   3. Payables Desk API & Web App (port 8000)
#
# Usage:
#   ./run_local.sh
# =============================================================================
set -eo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

# 1. Load .env if present
if [ -f .env ]; then
  set -a
  source .env
  set +a
  echo "[+] Loaded .env environment variables."
else
  echo "[!] Warning: No .env found. Using default environment."
fi

export STATE_STORE="${STATE_STORE:-postgres}"
export NETWORK="${NETWORK:-localhost}"
export SIGNING="${SIGNING:-client}"
export PER_COMPANY_CONTRACTS="${PER_COMPANY_CONTRACTS:-on}"
export PORT="${PORT:-8000}"
export AUTH_PORT="${AUTH_PORT:-3001}"
export PUBLIC_URL="${PUBLIC_URL:-http://127.0.0.1:8000}"

# Clean shutdown of all background processes on Ctrl+C
cleanup() {
  echo ""
  echo "[*] Shutting down all services..."
  trap - SIGINT SIGTERM EXIT
  kill 0 2>/dev/null || true
  wait 2>/dev/null || true
  echo "[*] All services stopped."
}
trap cleanup SIGINT SIGTERM EXIT

# 2. Check virtual environment
if [ -d .venv ]; then
  PYTHON="$ROOT_DIR/.venv/bin/python"
  UVICORN="$ROOT_DIR/.venv/bin/uvicorn"
else
  PYTHON="python3"
  UVICORN="uvicorn"
fi

# 3. Start local Hardhat chain if NETWORK=localhost
if [ "$NETWORK" = "localhost" ]; then
  echo "[+] Starting local Hardhat chain on 127.0.0.1:8545..."
  (cd chain && npx hardhat node --hostname 127.0.0.1 --port 8545 > /tmp/hardhat_node.log 2>&1) &
  
  echo "    Waiting for chain RPC..."
  for i in $(seq 1 30); do
    if curl -s -X POST -H 'Content-Type: application/json' --data '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}' http://127.0.0.1:8545 > /dev/null 2>&1; then
      break
    fi
    sleep 0.5
  done

  echo "[+] Deploying contracts to local chain..."
  (cd chain && npx hardhat run scripts/deploy.js --network localhost)
fi

# 4. Start Better Auth Login Service (port 3001)
if [ -n "$BETTER_AUTH_SECRET" ] && [ -n "$DATABASE_URL" ]; then
  echo "[+] Running Better Auth database migrations..."
  (cd auth && node server.mjs --migrate)
  echo "[+] Starting Better Auth service on 127.0.0.1:$AUTH_PORT..."
  (cd auth && node server.mjs) &
  echo "    Waiting for Better Auth service..."
  for i in $(seq 1 30); do
    if curl -s "http://127.0.0.1:$AUTH_PORT/health" > /dev/null 2>&1; then
      echo "    [+] Better Auth service is ready."
      break
    fi
    sleep 0.2
  done
else
  echo "[!] Warning: BETTER_AUTH_SECRET or DATABASE_URL not set; skipping Better Auth login service."
fi

# 5. Start API & Web Desk (port 8000)
echo "[+] Starting Payables Desk API & Web App at $PUBLIC_URL..."
$UVICORN apagent.api:app --host 0.0.0.0 --port "$PORT"
