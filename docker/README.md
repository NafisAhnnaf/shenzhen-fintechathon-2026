# Running the desk in one container

The image holds the API with the built web app, the login service (Better Auth), and a local demo chain on which
every company gets its own contracts. It keeps state in Postgres (Neon), sends and reads mail through AgentMail, and
anchors every company's journal on Base Sepolia once an hour.

```bash
docker build -t payables-desk .
docker run --env-file .env -e PUBLIC_URL=http://127.0.0.1:7860 -p 7860:7860 payables-desk
# open http://127.0.0.1:7860
```

## Settings

Required:

| Variable | What it is |
| --- | --- |
| `DATABASE_URL` | Postgres connection string (Neon: use the pooled one, with `sslmode=require`) |
| `BETTER_AUTH_SECRET` | Shared by the login service and the API; 32+ random characters |
| `APP_SECRET` | Signs the agent's saved working memory; 32+ random characters |
| `PUBLIC_URL` | The address people open, e.g. `https://<user>-<space>.hf.space`; invitation and reset links use it |

Optional:

| Variable | What it is |
| --- | --- |
| `GEMINI_API_KEY` | Reads PDF and photo invoices and routes requests (without it, JSON e-invoices and the rule router) |
| `AGENTMAIL_API_KEY`, `AGENTMAIL_INBOX` | The agent's mailbox (without it, mail is kept in a folder inside the container) |
| `MAIL_SANDBOX_TO`, `MAIL_LIVE` | Where supplier mail goes; `MAIL_LIVE=on` sends to the registered supplier addresses |
| `PUBLIC_ANCHOR_NETWORK=baseSepolia`, `AGENT_KEY` | Hourly public anchors; `AGENT_KEY` is the Base Sepolia agent key from `chain/.env` (it needs a little test ETH) |
| `MAILBOX_POLL_SECONDS` | How often the agent reads its inbox (default 120) |
| `DAILY_PAYMENT_CAP_USD`, `REQUEST_PER_MINUTE`, `REQUEST_PER_DAY` | Limits (defaults 250000, 6, 200) |

Generate secrets with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.

## Hugging Face Spaces (free)

1. Create a Space: SDK **Docker**, hardware **CPU basic** (free). A free Space must be public for judges to open it;
   the code becomes visible, the secrets do not.
2. Push this repository to the Space (or connect it to the GitHub repository). The Space reads the front matter
   below from its README; add it at the top of the Space's `README.md`:

   ```yaml
   ---
   title: Payables Desk
   sdk: docker
   app_port: 7860
   ---
   ```

3. In the Space's **Settings → Variables and secrets**, add the required settings as **secrets**, and `PUBLIC_URL`
   as the Space's own address.
4. The first build takes about ten minutes. A free Space sleeps after 48 hours without visitors; the next visit
   wakes it in about a minute. The demo chain starts fresh after a restart, so each company starts again from the
   sample records; accounts, companies and the public anchors stay (they are in Neon and on Base Sepolia).

## What runs inside

`docker/start.sh` starts the demo chain (Hardhat) on 127.0.0.1:8545 and deploys the base contracts, runs the login
service's migrations and starts it on 127.0.0.1:3001, then the API on `$PORT`. Only the API is reachable from
outside; it forwards `/api/auth/*` to the login service and relays the browser's chain calls (reads, and signed
transactions from signed-in members to their own company's contracts). If any process stops, the container stops
and the platform restarts it.
