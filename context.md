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
- Deck (plan in `pptx.md`: 13 slides + appendix, scripts, assets, rehearsal), demo video (section 11 script).
  Technical document and security self-assessment are written (see log).

Gaps found while writing the security self-assessment (section 10.4 there; none blocks the demo):
- R1 router state carries supplier-supplied invoice numbers untagged; R2 S5 checks bill cards only, and the
  fair-price justified price lacks the `market` tag; R5 contract supplier cap uses fixed weekly buckets (governor is
  rolling); R6 API has no authentication and a self-declared role; R7 arbiter defaults to the owner address.
- Dry run from a clean clone; Playwright browser tests (`cd web && npx playwright install chromium && npx playwright test`).

## Log

### 2026-10-20 · README story, landing page, live reader, reruns (PR #1, branch tabib/story-and-reruns)

- README: story, AFP 2026 figures, mermaid diagram, research formulas, eight animated SVG charts from `results/`
  (`docs/readme/make_charts.py`), screenshots and a live-reader GIF (captured by `web/media/capture.spec.ts`). The
  previous README (submission checklist and reference) follows unchanged.
- Landing page at `/` (styles scoped under `.lp` in `web/src/landing.css`; numbers fixed from `results/`).
- Live reader: `POST /api/documents/stream` (server-sent events) and `GET /api/bills/{id}/read`; the Inbox upload
  and phone photo open `components/ReaderPanel.tsx`; bills show "What the reader saw".
- Reader eval on this code: 434/435 fields exact (99.8%), 29 documents, gemini-3.5-flash-lite, 3.7 s each.
- The request box now defaults to the rule decider even with a model key (`DECIDER=llm` opts in): with the model,
  FISCO task 3 and browser flow 3 failed because it asked a question where the script expects a plan.

### 2026-10-19 · clickable prototype

- `design/prototype/` (index.html, README.md, assets/ with animated character SVGs and favicon) and
  `design/payables-desk-prototype.zip`: landing, wallet login, desk, bills, cases, risk, security, activity,
  settings, with sample data and a prototype-states panel. Online: https://claude.ai/artifact/66yyDr5y9PSM1xsDcmRyyu.

### 2026-10-18 · frontend design handoff

- UI spec canvas for the web app (12 boards: foundations, desk, plans, questions, bills, cases, risk, security,
  activity, phone, system states), light blue-purple theme: https://claude.ai/artifact/8rknqW24q6hSnzTb1oHJck.
  States marked “Proposed, not in the API yet” need backend work before they can be built.

### 2026-10-18 · illustrated deck

- Illustrated version (light blue-purple theme, vector characters, click-through animations):
  https://claude.ai/artifact/68FsXa8fHG3vWCx9WrAAYC. The earlier plain deck stays at the link below.

### 2026-10-18 · deck built

- The deck from `pptx.md` is built as a shared slides artifact (13 slides + appendix, speaker notes):
  https://claude.ai/artifact/UwffoQLnmF2bqHfpfFW8K2 (share it from its Share menu; edit there; exports to PPTX/PDF).

### 2026-10-18 · deck story

- `pptx.md` rewritten as one story, "The New Hire": the AI clerk's first month (day stamps, a cast with a
  recurring con artist, workplace metaphors only, a callback ending), with a fact sheet correcting claims from the
  team's draft.

### 2026-10-18 · deck plan

- `pptx.md`: plan for the 10-minute deck. One-liner, eight creative ideas (heist opening, recurring character,
  "every number has a passport", trust dial, hash receipts, mistake comic strip, live "Rob us" and phone-photo
  moments for the final), 13 slides with timing, on-screen content, script and source file, 8 appendix slides
  for Q&A, palette and type, asset capture list, build steps, rehearsal plan.

### 2026-10-18 · submission documents (uncommitted)

- `docs/security_self_assessment.md`: tiers T0/P/T1/T2/T3 with app and contract enforcement, S1-S10 with the
  enforcing code and refusing test, B1-B13, RED with method notes (naive column partly by construction; the contract
  column is exercised only by the direct-call and no-signature rows), Jev/LLM/VLM data handling ("Jev-ready
  interface"), known risks (plan section 5, S3 exception, stress case, gaps R1-R10, plan section 15 status).
- `docs/technical_document.md`: architecture and both flows, request layer (catalogue, `decide()`, conformal
  clarification with alpha_I 3% / alpha_S 5%), checker, risk core with the CRC and K(beta) derivations, AC-8 and
  CAPITAL, fair-price check (task 16 worked example), contracts, ERP adapters, stated limits; market watch under
  future work. Numbers checked against `results/` and `evidence/`.

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

## 2026-10-19: frontend built from the prototype design

- `web/` now uses the purple design in `design/prototype`. It adds new routes: `/` (landing), `/login` (wallet login by role), `/desk`, `/activity`, `/risk`, `/security`, `/settings` (payees and unfreeze, reserve mode, ERP re-read, demo next-day/skip/reset), and a not-found page.
- Banners appear across the app for: server unreachable, ledger/chain mismatch, wallet on the wrong network, agent paused.
- Characters are in `web/src/components/Characters.tsx`; the design CSS is in `web/src/proto.css`. Tailwind token names are kept and remapped to the new palette.
- E2E: 12/12 Playwright tests pass against the built app on :8000, after `/api/admin/reset`. Run them with `PW_CHANNEL=chrome npx playwright test` to use the installed Chrome.
