# Bonded payables agent

An AI accounts-payable agent for Hong Kong manufacturers (FinTechathon 2026, International Track, Topic F: Agent Wallet).
It reads supplier bills, checks them against the company's own records and public market prices, and pays routine bills
on its own. A smart contract enforces every payment rule, even if the agent's server is hacked. The owner sets a loss
budget; conformal risk control turns it into how much the agent may pay alone, and a certified bound sizes the reserve
that backs those payments.

The full design is in [`docs/plan.md`](docs/plan.md). All company and supplier names in the demo are invented.

## What is in the repo

| Path | What |
| --- | --- |
| `chain/contracts/` | `PaymentVault`, `BondPool`, `EvidenceAnchor`, `NaiveWallet` (demo baseline), `MockUSDC` (tUSDC) |
| `chain/test/` | Contract tests, one per invariant B1-B13 plus payment, reserve and claim rules |
| `apagent/checker.py` | Deterministic checker: supplier, order, lines, quantity, price, totals, credits, duplicates, fair price |
| `apagent/tags.py`, `policies.py` | Capability tags on every value and policies S1-S10 (CaMeL-style) |
| `apagent/injection.py` | Injection flag; decodes base64, Morse and look-alike characters first |
| `apagent/risk/` | Score, conformal risk control cut-offs, betting confidence bounds, Bernstein capital bound K(beta) |
| `apagent/governor.py` | Risk service that decides the tier and co-signs autonomous payments (EIP-712) |
| `apagent/agent.py` | The agent: process bills, pay, approve, reconcile statements, claims, recovery, supplier query, protective actions |
| `apagent/intent/` | Requests in plain words: intent catalogue, `decide(schema, state)` backends, conformal clarification, plan templates |
| `apagent/sim.py`, `demo.py` | Simulated company (2025, real World Bank metal prices) and the curated December demo documents |
| `apagent/tasks.py` | Scripted tasks; writes the execution evidence |
| `apagent/experiments.py` | AC-8, CAPITAL, FAIR, RED |
| `apagent/api.py` | HTTP API for the UI |
| `evidence/`, `results/` | Execution evidence (hashes) and experiment results |

## Setup

Requirements: Node 20+ (Hardhat warns on Node 25 but works), Python 3.12.

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
cd chain && npm install --legacy-peer-deps && npx hardhat compile && cd ..
```

On an external (exFAT) drive macOS writes `._*` files next to every file. Hardhat is configured to skip them. If Python
packages fail with errors such as `'._chinese_simplified' is not a valid Language`, run `find .venv -name '._*' -delete`.

## Run everything locally

```bash
# 1. Calibrate the risk core and build the demo world (writes data/calibration.json, data/demo/*)
.venv/bin/python -m apagent.risk.calibrate
.venv/bin/python -m apagent.demo

# 2. Start a local chain (keep it running) and deploy
cd chain && npx hardhat node &             # terminal 1
npx hardhat run scripts/deploy.js --network localhost && cd ..

# 3. Scripted tasks -> evidence/evidence_localhost.md
.venv/bin/python -m apagent.tasks --network localhost

# 4. Experiments -> results/summary.md (RED needs a fresh deployment first)
(cd chain && npx hardhat run scripts/deploy.js --network localhost)
.venv/bin/python -m apagent.experiments --red

# 5. API for the UI (owner and finance manager sign in their own wallets)
NETWORK=localhost SIGNING=client .venv/bin/uvicorn apagent.api:app --port 8000
```

## Web app

`web/` is the desk: React, TypeScript, Vite, Tailwind, wagmi/viem for wallets, TanStack Query, ECharts.

```bash
cd web && npm install --legacy-peer-deps
npx vite build                      # the API serves web/dist at http://127.0.0.1:8000
npm run dev                         # or: development server on :5173, proxying /api to :8000
npx playwright install chromium && npx playwright test   # browser tests against :8000 after /api/admin/reset
```

Pages: Desk (requests, inbox, bills, plans, approvals, journal), Risk and reserve (the dial and the reserve
comparison), Security (the poisoned-invoice split screen, red-team results, pause and frozen payees), Evidence
(tasks and hashes). The connected wallet's address decides what a person can do: the owner's key sees owner
actions, the finance manager's key sees approvals. On a local chain the wallet menu also offers the Hardhat dev
accounts, which the local node signs for. For phone approval through WalletConnect set `VITE_WC_PROJECT_ID`
(free from cloud.reown.com) before building; without it, open the desk in MetaMask Mobile's own browser.

## Inputs, signing and state

**Inputs are real files.** `POST /api/documents` takes a supplier document as received: a `.json` e-invoice
(read directly), or a `.pdf` / photo (read by the vision model; without `VLM_API_KEY` the API answers 503 and records
nothing). Emails arrive as raw RFC 822 text (`POST /api/emails`); the sender's domain must match a registered
supplier exactly, and a reply quoting a query ID (`Q-001`) goes to that query, with the credit-note number and amount
read from its text. Statements are `.csv` (`date,ref,kind,amount,against`) or `.json` (`POST /api/statements/{supplier}`).
The demo inbox folders (`data/demo/documents`, `inbox`, `statements`) hold the December files; `POST /api/inbox/...`
takes one through the same path as an upload.

**People sign in their own wallets.** With `SIGNING=client` the server holds only the agent, governor and
underwriter-service keys. The finance manager signs EIP-712 messages (`GET /api/bills/{id}/approval`,
`GET /api/cases/{id}/signing`) and posts the signature back; the server checks the signer before sending anything.
The owner sends settings, unpause and unfreeze transactions from their wallet (`GET /api/dial/tx`,
`GET /api/owner-tx/{action}`) and posts the transaction hash; the server checks it was mined, succeeded, came from
the owner key and went to the vault. On a local chain, import the Hardhat dev keys #0 (owner) and #3 (approver) into
the wallet. `SIGNING=server` (task runner, tests) holds every key.

**State is saved.** After every change the API saves its state to `data/state/<network>.pkl` and reloads it on start,
but only if it belongs to the deployed vault. `GET /api/state` reports `consistency` (ledger vs chain).
`POST /api/admin/reset` redeploys the contracts and reloads the baseline ledger together
(on a public network: `?confirm=redeploy`).

## Tests

```bash
cd chain && npx hardhat test && cd ..        # 28 contract tests
.venv/bin/python -m pytest tests             # 68 tests; the chain and API tests need the local node running
```

## FISCO BCOS (WeBank's chain)

The contracts compile with Solidity 0.8.11 and the `london` target, the newest FISCO BCOS v3 accepts, so the same
bytecode runs on Hardhat, Base Sepolia and FISCO. FISCO block timestamps are in milliseconds; the vault and the pool take
a time unit at deployment and read time only through `nowSeconds()`. Time cannot be moved forward on FISCO, so the demo
uses a short "day" for the daily caps (`DEMO_DAY_SECONDS`, default 180) and a 60-second payee cool-down.

```bash
chain/fisco/fisco.sh up                                          # four-node local chain, web3 RPC on :8546, chain id 20200
(cd chain && npx hardhat run scripts/deploy.js --network fisco)
.venv/bin/python -m apagent.tasks --network fisco                # real time: about 15 minutes
NETWORK=fisco SIGNING=client .venv/bin/uvicorn apagent.api:app --port 8000
chain/fisco/fisco.sh down
```

FISCO has no public explorer, so the desk links each hash to `/api/tx/<hash>`, which reads the receipt from the chain
and decodes our contracts' events. In the browser, the wallet menu offers local test keys for the owner and the finance
manager (the public Hardhat keys #0 and #3); they sign in the browser and send through the API's `/api/rpc` relay, which
forwards only reads and signed transactions.

## Base Sepolia

1. Create five separate test keys (owner, agent, governor, approver, underwriter), fund each with a little Base
   Sepolia ETH, and put them in `chain/.env` (see `chain/.env.example`).
2. `cd chain && npx hardhat run scripts/deploy.js --network baseSepolia`
3. Wait 5 minutes (payee cool-down), then `.venv/bin/python -m apagent.tasks --network baseSepolia`.

On a public testnet time cannot be moved forward. The task runner uses real waits for the claim window, but the
daily caps reset only at midnight UTC: run the four task days on separate days, or edit the runner to stop after each day.

## Backends and keys

- Reader: `SimReader` (calibration), `JsonReader` (clean JSON, the default for the demo), `VLMReader` (any
  OpenAI-compatible vision model, e.g. Qwen-VL; set `VLM_API_KEY`).
- Request router: `RuleDecider` (offline, default) or `LLMDecider` (set `DECIDER=llm` and `LLM_API_KEY`). Both return a
  probability for every option in a closed list; a Jev backend can implement the same `decide` method.

## Data

World Bank Commodity Price Data (The Pink Sheet), monthly, CC BY 4.0: `data/raw/CMO-Historical-Data-Monthly.xlsx`.
Everything else is simulated; rates are stated in `apagent/sim.py` (process errors) and `apagent/reader.py` (reader errors).
