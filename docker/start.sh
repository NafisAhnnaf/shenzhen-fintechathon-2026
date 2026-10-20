#!/usr/bin/env bash
# Starts the demo chain, deploys the base contracts, runs the login service, then the API in the foreground.
# If any of them stops, the container stops (and the platform restarts it).
set -euo pipefail
cd /app

: "${DATABASE_URL:?set DATABASE_URL (Neon Postgres)}"
: "${BETTER_AUTH_SECRET:?set BETTER_AUTH_SECRET}"
: "${APP_SECRET:?set APP_SECRET}"
export PUBLIC_URL="${PUBLIC_URL:-http://127.0.0.1:${PORT}}"

echo "starting the demo chain"
(cd chain && npx hardhat node --hostname 127.0.0.1 --port 8545 > /tmp/chain.log 2>&1) &
for i in $(seq 1 60); do
  curl -fs -X POST -H 'content-type: application/json' --data '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}' \
    http://127.0.0.1:8545 > /dev/null && break
  sleep 1
done
(cd chain && npx hardhat run scripts/deploy.js --network localhost | tail -3)

echo "login service: migrations, then start"
(cd auth && node server.mjs --migrate)
(cd auth && node server.mjs) &

echo "API on :${PORT}"
python -m uvicorn apagent.api:app --host 0.0.0.0 --port "${PORT}" --proxy-headers --forwarded-allow-ips='*' &

wait -n
echo "a process stopped; exiting"
exit 1
