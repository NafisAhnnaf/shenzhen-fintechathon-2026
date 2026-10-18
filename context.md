# Working context

A running log of coding changes against the plan (`docs/plan.md`, v3), what is done, and what is still open.
Add a dated entry at the top of the log for every batch of commits. Keep "Open items" current.

Submission target: **Mon 19 Oct 2026, 22:00 Dhaka**. Hard deadline: Tue 20 Oct, 21:59 Dhaka (23:59 UTC+8).

## How to run locally

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
(cd chain && npm install --legacy-peer-deps && npx hardhat compile)
(cd web && npm install --legacy-peer-deps && npx vite build)

(cd chain && npx hardhat node)                                         # terminal 1, keep running
(cd chain && npx hardhat run scripts/deploy.js --network localhost)    # fresh contracts
NETWORK=localhost SIGNING=client .venv/bin/uvicorn apagent.api:app --port 8000   # http://127.0.0.1:8000
```

- In the desk, the wallet menu offers the Hardhat dev keys: #0 is the owner, #3 the finance manager.
- Payees become active 300 s after deployment. Skip ahead with `curl -XPOST "127.0.0.1:8000/api/demo/advance?seconds=301"`.
- `POST /api/demo/next-day` moves the demo clock a day and anchors the day's log root on-chain.
- `POST /api/admin/reset` redeploys the contracts and reloads the baseline ledger.
- PDFs and photos need the vision reader (`VLM_API_KEY`); the inbox's JSON e-invoices work without it.

Checks:

```bash
(cd chain && npx hardhat test)                      # 28 contract tests
.venv/bin/python -m pytest tests                    # 88 pass; 4 Odoo tests skip unless Odoo runs
.venv/bin/python -m apagent.tasks --network localhost        # scripted tasks -> evidence/
.venv/bin/python -m apagent.experiments --red                # after a fresh deploy -> results/
VLM_API_KEY=... .venv/bin/python -m apagent.reader_eval      # reader accuracy -> results/reader.json
```

## Status against plan v3 (18 Oct)

| Area | Status |
| --- | --- |
| Contracts, invariants B1-B13 | Done; 28 tests pass |
| Scripted tasks | 20 of 21 plan tasks (+ reserve release and anchor) pass on localhost; task 17 depends on market watch (cut) |
| Policies S1-S10 | All enforced in code, each with a refusing test |
| Request bar, conformal clarification | Done; 100% intent and slot set coverage on 47 held-out requests |
| Risk core, K(beta), stress case | Done; correlated stress case reported in `results/summary.md` |
| Experiments AC-8, CAPITAL, FAIR, RED | Done; RED 0/14 attacks succeed with policies + contract |
| UI (desk, risk, security, activity, money tally) | Done; bill details show the source of every number |
| Market watch, BUY-AHEAD, task 17 | Cut (roadmap slide), as planned |

## Open items

Need something only the team has:
- **Vision reader key** (`VLM_API_KEY`, DashScope or any OpenAI-compatible VLM): then run `apagent.reader_eval`, and
  rerun tasks so task 2 uses the phone photo `data/demo/documents/t02_photo.jpg`.
- **Publicly checkable hashes**: five funded Base Sepolia keys in `chain/.env`, deploy, run the tasks there
  (README, "Base Sepolia"). Also ask the organisers whether testnet hashes count.
- **FISCO evidence rerun** (`chain/fisco/fisco.sh up`, about 15 minutes) so FISCO evidence includes today's changes.
- **Jev**: no Jev backend exists. Either add a `JevDecider` behind `decide()` with a key, or say "Jev-ready interface".

Not code, still to do (plan section 14):
- Technical document, security self-assessment, deck, demo video (section 11 script).
- Dry run from a clean clone; Playwright browser tests (`cd web && npx playwright install chromium && npx playwright test`).

## Log

### 2026-10-18 · branch `fix/plan-gaps`

- `82fed71` Policies: S4 refuses payee-changing tools by name; S5 checks every number on a bill card against its
  tagged source (`policies.check_card`, called in `Agent.bill_card`, tags returned with the card); S7 stops market
  values from setting a payee, amount or quantity; S8 refuses raw supplier text or untrusted values in the router
  state (`policies.check_router_input`, called in `Router.route`). New tests for S3-S8 and a card test on real bills.
- `c4efb8a` CAPITAL: correlated stress case (one supplier change hits 30 T1 bills, typical and total-loss severity,
  bounded by the per-supplier weekly cap). Summary also reports request-set coverage.
  Result: 0% of windows exceed K in every bundle, because P-SUPWEEK limits one supplier to $21,429 a window.
- `1ce8b05` `Session.close_day` anchors the decision-log Merkle root once per ledger day (called by `next_day`).
  `render.photo_from_pdf` and `t02_photo.jpg` (task 2 uses it when the VLM is configured).
  `apagent/reader_eval.py` measures the VLM against the JSON fields. PDF table columns no longer overlap.
- `e3517e4` Regenerated localhost evidence (22/22) and RED results.
- `757617c` Bill details in the desk list where each number comes from.
- `5739893` Numbers computed from a bill are labelled "calculated from the bill"; `.claude/launch.json` for the desk and chain.
