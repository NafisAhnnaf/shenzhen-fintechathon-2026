# Product spec: bonded payables agent

This file is the source of truth for what the system does. `docs/plan.md` is the original design and
`docs/technical_document.md` explains the methods. When they disagree with this file, this file wins.
Every feature has an ID, a status and the code and test that back it. Update the status when work lands.

## 1. What it is

**An accounts-payable agent that pays suppliers on its own when the records agree, asks a person when they don't,
and can prove every payment it made.**

Users: a Hong Kong manufacturer with 50–250 staff. The owner sets limits; the finance manager approves
exceptions; the agent does the routine work. Money sits in a smart contract that enforces the rules even if the
agent is wrong, tricked or hacked.

## 2. Glossary

Use these words, and only these, in code labels, UI, docs and the deck.

| Term | Meaning | Do not say |
| --- | --- | --- |
| Bill | A supplier invoice the company must pay | invoice payload, document |
| Paid by agent | Tier T1: the agent paid within its limits, co-signed by the governor | zero-click, autonomous settlement |
| Approved by finance manager | Tier T2: the finance manager signed the payment in their wallet | co-sign via FaceID, dual-key |
| Owner action | Tier T3: only the owner's wallet can do it (settings, payees, unpause, unfreeze) | multi-sig |
| Protective action | Tier P: an action that only reduces what can go out (hold, freeze, pause, probation) | quarantine |
| Risk setting | One of Careful, Standard, More, Most. Each sets the loss budget β and the daily limits | bundle, autonomy matrix |
| Loss budget (β) | The share of bill value the owner accepts losing on bills the agent pays alone | deviation tolerance |
| Limit for paying alone | The per-payment cap P-CAP ($5,000 in the demo) | velocity cap |
| Reserve | Money locked to repay mistakes on bills paid by the agent (`BondPool`) | escrow, insurance |
| Bank (underwriter) | The party that funds the reserve in bonded mode and earns a premium | insurer |
| Governor | The risk service that scores each bill and signs payments by agent | sentinel |
| Three-way match | Invoice vs purchase order vs goods received | 3-way ERP match verified |
| Market check | Price change on the bill vs the change in the material's public price index | fair-price oracle |
| Dispute | An open case: missed credit, overcharge query or reserve claim | ticket |
| Journal | The log of every action, who took it and its transaction | telemetry |
| Anchor | The daily Merkle root of the journal, stored on-chain | proof of state |
| Demo date | The ledger's "today" (10 Dec 2025 in the demo set) | |

## 3. Roles and permissions

| Action | Owner | Finance manager | Agent | Governor | Bank | Arbiter | Enforced by |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Read bills, journal, payments | ✓ | ✓ | ✓ | | ✓ (own pool) | | API session (X2) |
| Pay a bill alone (T1) | | | ✓ with governor signature | signs | | | `payAutonomous` |
| Pay an approved bill (T2) | | signs | sends | | | | `payApproved` |
| Second signature above the two-signature threshold | ✓ | | | | | | `payApproved` (D4) |
| Hold a bill, probation | | ✓ | ✓ | | | | policies S10 |
| Freeze a payee, pause the agent | ✓ | | ✓ | ✓ | | | `freezePayee`, `pauseAgent` |
| Unfreeze, unpause | ✓ | | | | | | owner-only functions |
| Add or change a payee | ✓ (after call-back) | | | | | | `addPayee` + cool-down |
| Change the risk setting | ✓ | | | | ✓ (bonded mode) | | `proposeSettings`, `approveSettings` |
| Send a supplier email | | ✓ (amount-changing) | ✓ (templates, see V2) | | | | policies S1, S6, S11 |
| Confirm a missed credit, file a claim | | signs | sends | | | | `openReceivable`, `fileClaim` |
| Dispute a claim | | | | | ✓ | | `dispute` |
| Settle a disputed claim | | | | | | ✓ | `resolve` |
| Fund or withdraw reserve | ✓ (self-reserve) | | | | ✓ (bonded) | | pool `fund` / `withdraw` |

Keys: the owner, finance manager, bank and arbiter use their own wallets. The agent key is on the API server.
The governor runs as a separate service with its own key (X5).

## 4. Bill lifecycle

```
received ──► checked ──┬─► scheduled ──► paid (by agent)
                       ├─► needs approval ──► paid (by finance manager)
                       │                  └─► rejected
                       ├─► on hold ──► needs approval (after call-back or supplier reply)
                       └─► rejected (duplicate)
paid ──► reconciled (statement matched) ──► closed
paid ──► disputed (missed credit) ──► recovered ──► closed
```

| UI status | Meaning | Code (`Bill.status`, `Bill.tier`) | Who moves it on |
| --- | --- | --- | --- |
| Received | Read, not yet checked | `received` | agent |
| Scheduled | Cleared for the agent to pay on its pay date | `approved`, `T1` | agent |
| Needs approval | Waiting for the finance manager's signature | `held`, `T2` | finance manager |
| On hold | Blocked until a person acts (bank change, unknown sender) | `held`, `hold` | owner or finance manager |
| Paid | Paid on-chain; shows who paid | `paid`, `T1` or `T2` | — |
| Rejected | Duplicate or refused | `rejected` | — |
| Disputed | A case is open against a paid bill | `paid` + open case | finance manager |

A paid or rejected bill never changes status again (X4).

## 5. Features by stage

Status: **Built** (in code, tested), **To build** (in scope, not done), **Roadmap** (not in this release).

### 5.1 Receive

| ID | Feature | Status | Code | Test |
| --- | --- | --- | --- | --- |
| R1 | ERP sync: live Odoo 17, CSV/Excel exports with column mapping | Built | `erp/` | `test_erp.py` |
| R2 | ERP presets for QuickBooks, Xero and Kingdee exports | To build | `erp/csvfiles.py` | |
| R3 | Bill intake: e-invoice JSON, PDF and photo through the vision reader | Built | `intake.py`, `reader.py` | `test_intake.py` |
| R4 | Mailbox: poll an IMAP inbox for bills (attachments) and supplier replies | To build | | |
| R5 | Supplier statements (CSV/JSON) | Built | `intake.parse_statement` | task 4 |
| R6 | Per-field reader confidence shown on the bill | To build | | |

### 5.2 Check

| ID | Feature | Status | Code | Test |
| --- | --- | --- | --- | --- |
| C1 | Three-way match: supplier, order, lines, received quantity, price tolerance, totals, credits | Built | `checker.py` | `test_checker.py` |
| C2 | Duplicates, exact and fuzzy (Fellegi–Sunter weights) | Built | `checker.find_duplicate` | task 2 |
| C3 | Market check against World Bank indices (pass-through, lag) | Built | `checker`, `market.py` | task 16, FAIR |
| C4 | Market check fallback: the supplier's own price history when no index exists | To build | | |
| C5 | Currencies HKD, CNY, USD with a dated reference rate | To build | | |
| C6 | Mainland e-invoice (fapiao) check against a verification service (simulated in the demo) | To build | | |
| C7 | Hidden-instruction detector, patterns after decoding | Built | `injection.py` | RED |
| C8 | Hidden-instruction detector backed by a model, next to the patterns | To build | | |
| C9 | Supplier-signed bills: a registered supplier signs the bill hash | To build | | |
| C10 | Market watch: 90% price range, alert, buy-ahead suggestion | To build | | |

### 5.3 Decide

| ID | Feature | Status | Code | Test |
| --- | --- | --- | --- | --- |
| D1 | Governor: risk score, cut-off per group, caps, reserve, tier and reasons | Built | `governor.py` | `test_agent.py` |
| D2 | Cut-offs by conformal risk control; reserve by betting bounds and Bernstein | Built | `risk/` | AC-8, CAPITAL |
| D3 | Drift guard and supplier probation after a confirmed mistake | Built | `governor.outcome`, `agent.probation` | task 4 |
| D4 | Two signatures above a threshold for approved payments | To build | `PaymentVault.sol` | |
| D5 | Budgets per cost centre | To build | | |
| D6 | Requests in plain words: intent, one question when unsure, plan, run | Built | `intent/` | tasks 19–21 |

### 5.4 Pay

| ID | Feature | Status | Code | Test |
| --- | --- | --- | --- | --- |
| P1 | Payments by agent and by finance manager through the vault | Built | `PaymentVault.sol`, `chain.py` | B1–B13 |
| P2 | Bank rail for mainland payees | Built | `_send` | task 15 |
| P3 | Pay-date planning (early-payment discounts, cash floor) with a schedule screen | Built (screen to build) | `agent.plan_dates` | task 13 |
| P4 | Early-payment offers to suppliers | To build | | |
| P5 | Rolling 7-day supplier cap in the contract | To build | `_applyCaps` | |

### 5.5 Protect

| ID | Feature | Status | Code | Test |
| --- | --- | --- | --- | --- |
| X1 | Freeze, pause, circuit breaker, cool-down on new payees | Built | vault, `agent.py` | tasks 6, 9, 10, 14 |
| X2 | Sign-in with the wallet; the server checks the role on every request; CORS limited to the app | Built | `auth.py`, `api.py` | `test_api.py` |
| X3 | Owner transactions checked by function and arguments; a transaction hash is accepted once | Built | `chain.verify_sent`, `agent._verify_once` | `test_api.py` |
| X4 | State guards: paid and rejected bills are final; consistency check covers payees and settings | Built | `agent.reject`, `session.consistency` | `test_api.py` |
| X5 | Governor as a separate service with its own key; re-checks every bill before signing | Built | `governor_service.py` | `test_governor_service.py` |
| X6 | Independent arbiter key | Built | `deploy.js` | deploy refuses owner, bank or agent |
| X7 | Supplier onboarding and bank change: call-back checklist, owner signs, cool-down | To build | | |
| X8 | Try-your-own attack: type any invoice text and send it to both agents | To build | | |

### 5.6 Resolve

| ID | Feature | Status | Code | Test |
| --- | --- | --- | --- | --- |
| V1 | Supplier query and reply classification (credit note, bank-detail request, other) | Built | `agent.draft_query`, `receive_reply` | task 16 |
| V2 | The agent sends emails itself (templates, registered contact only, see S11) | To build | | |
| V3 | Statement reconciliation, receivable, reserve claim, recovery from the next bill | Built | `agent.reconcile` … | tasks 4, 5 |
| V4 | Claim dispute by the bank and decision by the arbiter | Built in contract (screens to build) | `BondPool.sol` | contract tests |
| V5 | Refund request when no later bill exists to deduct from | To build | | |
| V6 | Disputes page with a timeline per case | To build | | |

### 5.7 Prove

| ID | Feature | Status | Code | Test |
| --- | --- | --- | --- | --- |
| E1 | Journal: every action with its actor and transaction | Built | `audit.py` | |
| E2 | Daily anchor of the journal's Merkle root | Built | `session.close_day` | task anchor |
| E3 | Payments register: who paid, rail, transaction, filter by period and payer | To build | | |
| E4 | Verify: Merkle proof of a journal line against its anchor | To build | | |
| E5 | Month-end close pack | To build | | |
| E6 | Evidence on a public testnet (Base Sepolia) and FISCO BCOS | Needs keys | `tasks.py` | |
| E7 | Bank console: exposure, premiums, settings approval, claim disputes | To build | | |
| E8 | Notifications when something needs a signature | To build | | |

Roadmap (not in this release): one agent serving several companies; CBDC rails such as e-HKD or mBridge;
automatic buying from market watch.

## 6. User flows

Each flow names its actor, what starts it, what it changes on-chain, and the test that proves it.

| ID | Flow | Actor | Trigger | On-chain effect | Test |
| --- | --- | --- | --- | --- | --- |
| UF1 | Routine bill paid by agent | agent | bill arrives | `PaidAutonomous`, reserve locked | task 1 |
| UF2 | Bill needs approval; manager signs the proposal | finance manager | bill above a limit or flagged | `PaidApproved` | task 16, e2e |
| UF3 | Market check holds an overcharge; supplier queried; credit note; pay | agent, finance manager | price above market | `PaidApproved` | task 16 |
| UF4 | Duplicate rejected | agent | same bill resent | none | task 2 |
| UF5 | Bank change or hidden instruction: hold, freeze, call-back, owner restores | agent, owner | bill or email | `PayeeFrozen`, later `PayeeAdded` | tasks 6, 7 |
| UF6 | Request in plain words: question, plan, run, cancel | owner, finance manager | typed request | per step | tasks 19–21 |
| UF7 | Missed credit found in a statement; claim; recovery | agent, finance manager | statement | receivable, claim, offset | tasks 4, 5 |
| UF8 | Owner changes the risk setting; bank approves in bonded mode | owner, bank | Risk page or request | `SettingsActivated` | tasks 3, 18 |
| UF9 | Pause and resume | anyone (pause), owner (resume) | button or breaker | `AgentPaused`, `AgentUnpaused` | task 14 |
| UF10 | Agent emails the supplier and reads the reply | agent | query, payment, receipt | none | V2 tests |
| UF11 | Review payments for a period and verify one | any signed-in role | Payments page | none (reads anchor) | E3, E4 tests |
| UF12 | Add a supplier or change bank details | owner | Suppliers page | `PayeeAdded` after cool-down | X7 tests |
| UF13 | Bank reviews exposure and disputes a claim | bank | Bank console | `ClaimDisputed` | V4, E7 tests |

## 7. Policies

S1–S10 are in `docs/plan.md` section 5 and enforced in `apagent/policies.py`, each with a refusing test.
New in this release:

| ID | Rule |
| --- | --- |
| S11 | An email the agent sends goes only to the supplier's registered contact, is built from a fixed template filled with typed values (never supplier text), and never asks for, confirms or changes bank details. An email that changes what the company will pay needs the finance manager first. |

## 8. Research methods and where they are used

| Method | Source | Stage | Code | Evidence |
| --- | --- | --- | --- | --- |
| Capability tags, quarantined reader, policies before tool calls | CaMeL, Debenedetti et al. 2025 | Protect | `tags.py`, `policies.py` | RED: 0 of 14 attacks succeed |
| Conformal risk control for the pay-alone cut-off | Angelopoulos et al., ICLR 2024 | Decide | `risk/crc.py` | AC-8: loss under β in every setting |
| Conformal prediction sets for when to ask | KnowNo, Ren et al. 2023 | Decide | `intent/router.py` | 100% set coverage on held-out requests |
| Betting confidence bounds | Waudby-Smith & Ramdas, JRSS-B 2024 | Decide | `risk/capital.py` | CAPITAL |
| Bernstein bound for the reserve | — | Pay | `risk/capital.py` | CAPITAL: 7× less than per-payment reserves |
| Record linkage weights for duplicates | Fellegi & Sunter 1969 | Check | `checker.find_duplicate` | task 2 |
| Drift guard on the cut-off | online conformal update | Decide | `governor.outcome` | task 4 |
| Adaptive conformal price ranges | Gibbs & Candès 2021 | Check (C10) | to build | |

## 9. Screens

The layout follows common accounting tools: left sidebar, tables with status tabs, a detail panel. Approved mockup:
https://claude.ai/artifact/Qtxk5zanrCQcpJKZfr5oAT

| Screen | Contents | Features |
| --- | --- | --- |
| Inbox | New bills, emails and statements; upload and camera | R3, R4, R5 |
| Bills | Tabs by status; detail panel with three-way match, checks and proposal | C1–C10, D1 |
| Approvals | Queue of bills that need a signature, with the agent's proposal | UF2, D4 |
| Payments | Period selector, totals by payer, register with verify | E3, E4 |
| Suppliers | Registry, frozen state, onboarding and bank-change flow | X7, C9 |
| Disputes | Cases with timelines, claims, refunds | V3–V6 |
| Activity | Journal with filters and period | E1, E2 |
| Risk | Risk setting, reserve, guarantee figures | D2, UF8 |
| Security | Pause, frozen payees, attack demo, try-your-own | X1, X8 |
| Bank | Exposure, premiums, approvals, disputes (bank wallet only) | E7 |
| Settings | ERP, mailbox, team wallets, demo clock | R1, R4 |

Visual rules: neutral greys, system font, one ink colour for primary buttons, colour only for status. No
illustrations, gradients or "AI" badges. Every number on screen comes from the API.

## 10. Vision → features

| Vision | Features |
| --- | --- |
| Read ERP data from Odoo and other vendors | R1, R2 |
| Read emails and invoices | R3, R4, R5, R6 |
| Cross-check everything and pay the right person | C1, C2, C9, D1, P1, S1 |
| Prevent fraud and scams | C7, C8, C9, X1–X8 |
| Resolve mistakes | D3, V1, V3–V6 |
| Compare with market prices and report outliers | C3, C4, C10 |
| Draft and send emails on its own | V1, V2, S11 |
| Trace what the agent did vs people | E1–E5 |
| Research-grade methods in the right places | section 8 |
