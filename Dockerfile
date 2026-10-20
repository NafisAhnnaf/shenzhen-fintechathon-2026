# One container for the hosted demo: the API with the built web app, the login service, and a local demo chain
# (fresh contracts per company). State lives in Postgres (Neon), mail in AgentMail, and every company's journal is
# anchored hourly on Base Sepolia. Secrets come from the environment, never the image (see docker/README.md).
#
#   docker build -t payables-desk .
#   docker run --env-file .env -p 7860:7860 payables-desk

# Base images; pass e.g. --build-arg REGISTRY=public.ecr.aws/docker/library/ to use a mirror.
ARG REGISTRY=
FROM ${REGISTRY}node:20-bookworm-slim AS web
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM ${REGISTRY}node:20-bookworm-slim AS node
WORKDIR /app
COPY chain/package.json chain/package-lock.json chain/
RUN cd chain && npm ci --no-audit --no-fund
COPY auth/package.json auth/package-lock.json auth/
RUN cd auth && npm ci --omit=dev --no-audit --no-fund
COPY chain/ chain/
COPY auth/ auth/
RUN cd chain && npx hardhat compile

FROM ${REGISTRY}python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
 && apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/* \
 && useradd -m -u 1000 app
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY --chown=app:app apagent apagent
COPY --chown=app:app data data
COPY --chown=app:app evidence evidence
COPY --chown=app:app results results
COPY --chown=app:app --from=node /app/chain chain
COPY --chown=app:app --from=node /app/auth auth
COPY --chown=app:app --from=web /app/web/dist web/dist
COPY --chown=app:app docker/start.sh start.sh
RUN mkdir -p data/state && chown -R app:app data/state chain/deployments && chmod +x start.sh
USER app

# Defaults for the hosted demo; override any of them with environment variables.
ENV PORT=7860 NETWORK=localhost SIGNING=client STATE_STORE=postgres PER_COMPANY_CONTRACTS=on RPC_PUBLIC=/api/rpc \
    AUTH_PORT=3001 AUTH_SERVICE_URL=http://127.0.0.1:3001 API_INTERNAL_URL=http://127.0.0.1:7860 \
    PUBLIC_ANCHOR_SECONDS=3600 MAILBOX_POLL_SECONDS=120
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s CMD curl -fs http://127.0.0.1:${PORT}/api/health || exit 1
CMD ["./start.sh"]
