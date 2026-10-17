# Bonded payables agent: final build plan (v3)

**Track:** Agent Wallet. Theme: AI as a Financial Participant.
**Deadline:** 20 Oct 2026, 23:59 UTC+8 (21:59 Dhaka). **We submit:** Mon 19 Oct, 22:00 Dhaka. Tue 20 Oct is buffer.

> **What changed in v2 (Fri 16 Oct, night).** The agent now takes requests in plain words, shows a plan, asks one question when a request has more than one reading, and carries the plan out under the normal rules (3.6). It acts on its own in more places: it reconciles supplier statements and finds its own mistakes, proposes a resolution for every held bill, runs the dispute loop with suppliers, and takes protective actions such as freezing a payee or pausing itself (3.7). Jev is the decision model for requests, supplier replies and injection flags, with an LLM fallback behind the same interface (3.8). New policies S8–S10, agent rights to freeze and pause (7.2), tasks 19–21 and rewritten tasks 3, 4, 6, 7, 14, 16, the INTENT experiment, and updated video, team, schedule, risks and judges' questions. Market watch is now built only after the request layer works.

> **What changed in v3 (Fri 16 Oct, late night).** Scope cuts. One reader (VLM) instead of two; no OCR reading B and no harsh degradation level. The supplier dispute loop shrinks to one query and one canned reply (credit note). 100 owner requests instead of 300. Four experiments instead of ten: AC-8, CAPITAL, FAIR, RED.

---

## 1. Summary

**What we build.** An AI accounts-payable agent for Hong Kong manufacturers with 50 to 250 staff. It reads supplier bills, checks them against the company's own records and market prices, and pays routine bills alone. Every other bill goes to a person with a proposed resolution. The owner and the finance manager can tell it what to do in plain words: it shows a plan, asks when a request is unclear, and carries the plan out within the limits. It reconciles supplier statements, queries suppliers about wrong prices, and finds and recovers its own mistakes. It also watches the prices of the company's raw materials and drafts purchase orders ahead of large moves when the owner agrees.

**Five things make it different.**
1. **Safe by design.** Untrusted text (bills, supplier messages, market notes) never chooses a payee, an amount or the next step. The agent plans only from the owner's request and the company's own records. Code and a smart contract enforce every payment rule, even if the agent's server is hacked.
2. **An agent you can instruct.** The owner types "pay Acme's bills due this week except the disputed one". A fast decision model (Jev) maps the request to a typed action. The agent shows the plan, asks one question when the request has more than one reading, and runs it step by step under the normal rules.
3. **Controlled autonomy.** The owner sets a loss budget. A statistical guarantee turns it into how much the agent may do alone, per type of bill, and the agent tightens itself after every mistake.
4. **Market intelligence that acts.** A fair-price check holds bills whose price rose faster than the market justifies, and drafts the query to the supplier. A market watch forecasts a price range for each input and drafts a buy-ahead order when the owner accepts.
5. **An optional backstop.** For mistakes that get through, the company can run with no reserve, with its own reserve, or with a bank-funded bond pool. In the last two modes we calculate the reserve needed for a given level of autonomy, with a 99% guarantee.

> An AI payables clerk that takes instructions in plain words, cannot be robbed, catches overcharging and its own mistakes, and knows exactly how much it is safe to let it do alone.

---

## 2. The problem

- Finance staff check every supplier bill by hand, and reconcile supplier statements by hand at month-end.
- 76% of US organisations faced payments fraud in 2025 (AFP 2026 Payments Fraud and Control Survey).
- Suppliers pass on raw-material price rises, and sometimes more than the rise. Small firms rarely check invoice prices against market indices.
- Raw-material prices swing sharply, and small manufacturers buy at whatever the price is when they need the material.
- Companies do not let an AI agent move money alone, because agents can be tricked and nobody is liable when they are wrong. Agent providers often disclaim damages from errors (Xu et al. 2026).

---

## 3. How it works

### 3.1 Parties

| Party | Role |
| --- | --- |
| Company (owner, finance manager) | Sets rules and limits. Gives requests in plain words. Approves exceptions. Pays premiums in bonded mode. |
| AI agent | Reads documents, understands requests, builds and runs plans, reconciles statements, proposes resolutions, writes explanations and supplier queries, sends transactions. Holds no money and no admin rights. |
| Decision model (Jev) | Maps a request, a supplier reply or a piece of supplier text to one option from a fixed list, with probabilities. Never sets an amount, a payee or a tier. |
| Governor | Deterministic risk service. Scores bills and co-signs every autonomous payment. Run by the company, or by the underwriter in bonded mode. |
| Smart contract | Holds the rules: registered payees, caps, one payment per bill, signatures, reserves, claims. |
| Underwriter (bonded mode only, host bank in the demo) | Funds the bond pool. Earns premiums. |
| Supplier | Gets paid on time. Answers queries. |

### 3.2 Flows

**Every bill**

```
Document arrives (PDF, email export, phone photo)
  → Reader: isolated vision-language model (no tools, no keys, schema output only)
  → Injection flag (Jev): text that looks like instructions → T2 + security log
  → Checker: arithmetic, tax, order and goods-receipt match, duplicates, fair-price check
  → Governor: risk score vs the cut-off for this bill's group
       ├─ Low risk → T1: pick pay day → governor signs → contract checks (and locks a reserve) → agent pays
       └─ Other    → T2: approval card with evidence and a proposed resolution → finance manager signs → agent pays
  → Every step is logged. A daily Merkle root goes on-chain.
```

**Every request from the owner or finance manager**

```
User types a request in the request bar
  → Intent router (Jev): intent + slots, each with probabilities (trusted state only, no supplier text)
  → Clarification rule (conformal sets):
       one reading       → plan preview
       2–3 readings      → one question with buttons
       none / unsupported → "I can't do that here" + what it can do
  → Planner: fills the fixed template for that intent → visible step list
  → User taps Run (nothing with an external effect runs before this)
  → Each step runs through the normal path: checker, governor, tiers, contract
  → Live status per step; Cancel stops the remaining steps; results and hashes in the log
```

### 3.3 When the agent gets one wrong

1. A supplier puts a $1,140 credit for returned goods in a page-2 footer. Nobody recorded the return.
2. The reader misses it. Order and goods receipt match the gross amount. The agent pays $4,000 alone (correct: $2,860).
3. **The agent finds its own mistake.** At month-end it reconciles the supplier's statement against the ledger, finds a $1,140 credit the ledger does not have, and opens a "possible missed credit" case with the statement line and the bill.
4. The finance manager confirms with one tap. The overpayment is recorded as a receivable.
5. Bonded or self-reserve mode: the agent drafts the claim with its evidence, the manager signs it, and the reserve repays the company. Standard mode: the receivable stays open.
6. The cut-off for that group drops. The agent puts the supplier on probation: the next 5 bills go to a person.
7. **The agent recovers the money itself:** it deducts $1,140 from the supplier's next invoice and records the recovery (and returns it to the reserve, if one paid out).

The agent finds, reports and fixes the mistake. A person only confirms it. Every step has a transaction hash or a log line.

### 3.4 Permission tiers

| Tier | Actions | Control |
| --- | --- | --- |
| T0 | Read bills and balances. Answer questions and run what-if checks. Show plans. Draft bills, purchase orders, claims and supplier queries. Explanations | Automatic. Drafts need a person to post, sign or send them |
| P (protective) | Hold a bill, freeze a payee, pause itself, put a supplier on probation, deduct a confirmed receivable from the next invoice | Automatic. These only reduce money out or the agent's authority. Undoing them needs the owner or the normal tier |
| T1 | Pay a registered payee within all caps | Automatic. Contract checks caps, governor signature and (in reserve modes) the reserve |
| T2 | Above the cut-off or caps, new payees, probation, fair-price flags, credit-line draw, claims, sending a supplier query | Finance manager signs (EIP-712) or taps once |
| T3 | Payees, caps, settings, mode, funding, unfreeze, unpause | Owner key (plus underwriter key for bonded settings). The agent can prepare a settings change from a request; only the owner key can sign it. The agent key cannot call these |

The owner, the governor or the agent itself can **pause** the agent at any time; all bills then go to T2. Only the owner can unpause. The circuit breaker uses the same switch.

### 3.5 Backstop modes

| Mode | Who funds the reserve | What a mistake costs the company | Reserve per T1 payment |
| --- | --- | --- | --- |
| Standard | Nobody | The loss, as with a human clerk (minus what the agent recovers) | None. Caps limit exposure |
| Self-reserve | The company's own treasury | Paid from its own reserve, sized by K(β) | r = K(β)/N |
| Bonded | Underwriter (bank) | Repaid by the pool, for a premium | r = K(β)/N |

The prevention layers are the same in all three modes. The demo runs in bonded mode and shows a switch to standard mode.

### 3.6 Requests in plain words (intent layer)

The owner and the finance manager type requests in a request bar. The agent turns each request into one intent from a fixed catalogue, fills its slots from closed lists, and shows the plan before anything happens.

**Intent catalogue (v1)**

| Intent | Example request | Slots (all from closed lists) | Plan template | Control |
| --- | --- | --- | --- | --- |
| ASK-STATUS | "What do we owe Acme this month?" | supplier, window | Query ledger → answer card | T0 |
| ASK-WHY | "Why was bill 412 held?" | bill | Load decision log → explainer → card | T0 |
| WHAT-IF | "What happens to cash if we pay all copper bills today?" | bill filter, date | Select bills → payment planner simulation → cash chart | T0 |
| PAY-SET | "Pay Acme's bills due this week except the disputed one" | supplier, window, exclusions (disputed, flagged, on probation, above cap) | Select → re-check each bill → governor tier per bill → preview → Run: T1 payments, T2 cards → report | T1 / T2 per bill |
| HOLD-SET | "Hold all copper bills until the index updates" | supplier or material, until | Select → hold → log | P |
| RELEASE | "Release the Acme hold" | supplier or bill | Select → re-check → normal tiers. A fair-price hold always goes to T2 | T1 / T2 |
| QUERY-SUPPLIER | "Ask Acme about the price on bill 412" | bill, topic | Draft templated query → preview → send (one tap) → wait for reply (3.7) | T2 (one tap) |
| TIGHTEN | "Be more careful with Jiangxi Copper" | supplier | Probation for the next 5 bills | P |
| SET-DIAL | "Be more careful this month" / "Let it pay more on its own" | bundle | Show T1 share, caps, K and r for each bundle → prepare the settings transaction → owner signs | T3 |
| PAUSE / RESUME | "Stop all payments" / "Start again" | none | Pause (automatic) / prepare unpause transaction → owner signs | P / T3 |
| BUY-AHEAD (if market watch is built) | "Should we buy copper now?" | material, option | Market card → PO draft | T0 draft |
| UNSUPPORTED | "Add this new bank account" | none | Say what it can do, with three example requests | None |

One action per request. Filters and exclusions are slots. If the router finds more than one action in a request, it asks which one to do first. Jev handles up to 255 options per question; for larger lists (open bills) it chooses in two stages, supplier first.

**When it asks (conformal clarification).** We follow KnowNo (Ren et al. 2023), which uses conformal prediction sets to decide when a planner should ask for help.
- On calibration requests, the score is 1 − p(true intent). q̂ is the ⌈(n+1)(1−α_I)⌉/n quantile of the scores. At run time the set holds every intent with p ≥ 1 − q̂. The same rule gives a set for the request's key slot (supplier, bill or bundle) at level α_S.
- With α_I = 3% and α_S = 2%, the correct reading is in both sets at least 95% of the time, if new requests resemble the calibration requests. This holds whatever Jev's own calibration; better probabilities only make the sets smaller, so the agent asks less.
- One intent and one slot value: show the plan. Two or three: ask one question with them as buttons. More than three, or only UNSUPPORTED: say what it can do. A required slot missing from the request: ask for it, with the top candidates as buttons.
- Never more than one question per turn.

**Preview and run.**
- The preview lists every step. For PAY-SET it lists each bill with supplier, amount (`computed:erp_bounded`), tier and reason, the total, cash after payment, and what needs a signature. Buttons: Run, Edit (change a slot), Cancel.
- Run executes the steps in order. Each step checks the state and the policies again. If anything changed since the preview (a new bill, a freeze, a cap reached), that step stops and the agent asks.
- Cancel stops the remaining steps at any time. Payments already sent stay sent; a wrong one follows the normal recovery path.
- Each step writes a log line with the plan ID. The action log names the actor of each step: proposed by the agent, approved by the governor or a person, executed by the contract.

**Roles.** The finance manager can use every intent except SET-DIAL and RESUME (owner only).

**What a request cannot do.** Add or change payees, change bank details, move funds out of the vault or pool, pay a supplier not in the registry, or pay more than the ERP-bounded amount. The catalogue has no such intents, so these requests return UNSUPPORTED and the UI points to the owner's settings page (T3).

### 3.7 What the agent does on its own

**Statement reconciliation.** When a supplier statement arrives, and at month-end for every active supplier, the agent reads the statement (quarantined reader), matches each line to the ledger, and opens a case for every unmatched credit or charge. A missed credit becomes a receivable after the manager confirms it (section 3.3).

**A proposed resolution for every held bill.** T2 cards show a decision, not only evidence.

| Mismatch | Proposed resolution |
| --- | --- |
| Price above the order tolerance | Pay at the order price; hold the difference; draft a query |
| Fair-price excess | Pay at the justified price; hold the excess; draft a query |
| Quantity above received | Pay for the received quantity; hold the rest |
| Unrecorded credit or open receivable | Pay net of it |
| Duplicate (exact or fuzzy) | Reject; tell the supplier |
| New or changed bank details | Hold; open the call-back task |
| No order, or a tie between orders | Hold; ask the manager to pick the order |

All amounts are computed from ERP values and carry `computed:erp_bounded`. The manager approves, edits or rejects.

**Supplier query (one canned reply).**
1. The agent drafts a query from a template with typed values only (bill, line, prices, index). The recipient is the registered contact. The manager sends it with one tap.
2. The demo uses one canned reply: a credit note. It arrives through intake. The quarantined reader extracts typed fields (credit note number, amount). Jev classifies the reply: credit note, bank-detail request, or other.
3. Next step: credit note → checker matches it, the agent records it and proposes payment net of it. Bank-detail request → policy S4 (freeze and call-back). Other → manager.

No reply class leads to paying more than the current proposed amount. Revised invoices, disputes and reminders are on the roadmap.

**Protective actions.**

| Trigger | Action | Who undoes it |
| --- | --- | --- |
| Bank-detail change in a supplier message | Freeze that supplier on-chain; open the call-back task | Owner |
| Supplier text flagged as instructions (Jev), or a policy block | Bill to T2; security log | Not needed |
| P-BREAK blocked attempts | Pause itself on-chain | Owner |
| Confirmed error | Probation: the supplier's next 5 bills go to T2 | Automatic after 5 clean bills |
| Fair-price excess | Hold the bill | Manager decision |
| Pool free capital below P-CAP | All bills to T2 | Funder tops up |

Untrusted values can trigger these only against the supplier they came from.

### 3.8 Where Jev is used

Jev (TypeSafe AI, early access since 15 Sep 2026) is a decision model: text and structured state in, a choice from options defined in advance out, with a probability for each option. It produces no free text and cannot return a value outside the schema. TypeSafe reports 70–500 ms per call.

| Use | Input | Output | Trust |
| --- | --- | --- | --- |
| Intent router (core) | Request text + trusted state (registry names, open bill IDs, bundles) | Intent and slots, with probabilities | `intent`; preview before any effect (S9) |
| Reply classifier | Supplier reply text (quarantined) | Reply class | Untrusted; next steps never pay more |
| Injection flag | Raw supplier text | Probability that the text contains instructions to the system | Untrusted; can only escalate |
| Score feature (stretch) | Typed facts only | Probability that the bill needs review | Used in the score; kept only if AC-8 shows a higher T1 share at the same β |

**Fallback.** All calls go through one interface, `decide(schema, state) → {option: p}`. A second backend runs an LLM with schema-constrained output (TypeSafe's open System One adapter, or Qwen with a JSON schema). A config setting picks the backend. The demo runs with either.

**What Jev never does.** Set an amount, a payee or a tier; see a key; write text that a user reads.

**Limits.** "No type errors" means no answer outside the list. A wrong answer from the list is still possible; the conformal sets and the preview handle that. Calls send text to a US service in early access, so the hackathon uses demo data only. Production use needs a data agreement or a self-hosted model.

---

## 4. Scope

**In scope**
- Intake from a folder (PDF, image, email export).
- One reader: a VLM with schema output only. Clean JSON invoices as the fallback.
- Security layer with capability tags and policies (section 5).
- Deterministic checker with fair-price check (sections 6 and 9).
- Governor: score, cut-offs, settings bundles, certified capital, drift guard, probation, co-signature.
- **Request bar:** intent router (Jev, with LLM fallback), conformal clarification, plan templates for the catalogue in 3.6, preview, run, cancel.
- **Agent actions:** statement reconciliation, proposed resolutions for T2 bills, supplier query with one canned reply, protective actions (3.7).
- **Jev injection flag** on supplier text.
- Greedy payment-date planner: takes early-payment discounts that pay off, keeps cash above a floor.
- Fraud guard: bank-detail freeze, injection isolation, limit-splitting check, circuit breaker.
- Self-recovery: offsets a confirmed overpayment against the supplier's next invoice.
- ERP adapter on CSV.
- Contracts `PaymentVault`, `BondPool`, `EvidenceAnchor`, with the three backstop modes.
- Two rails: tUSDC on a testnet, or a simulated bank transfer that the vault records with the same checks.
- UI: request bar and plan view, bills, approval card with proposed resolution, fair-price card, risk dial, backstop panel, security log with actor column, money counter.
- Market watch: price-range forecast, alerts, buy-ahead suggestion, PO draft (section 9). **Built only after the request bar works end to end; first cut.**

**Out of scope (roadmap slide):** a second OCR reading, harsh document degradations, a full supplier dispute loop (revised invoices, disputes, reminders), automatic buying without the owner, commodity trading or hedging, news reading, real ERP, live email and messaging connectors, free-form plans or code written by a model, requests outside the intent catalogue, sending supplier messages without a tap, federated calibration across companies on FATE, cross-chain, escrow, a licensed insurance product.

**Stretch:** deploy `EvidenceAnchor` on the host bank's open-source chain and show one anchored root. Jev score feature (3.8).

**Compliance words**
- "Performance reserve" or "bond", never "insurance policy". Testnet only, mock stablecoin (tUSDC).
- Payees in mainland China and Bangladesh use the bank rail only.
- Market watch gives a range and a suggestion. It never trades and never buys without the owner.
- The agent key cannot fund, withdraw, add payees, unfreeze, unpause or change caps or mode.
- Jev runs on demo data only.

---

## 5. Security layer (CaMeL-style)

Supplier text can carry hidden instructions. Telling a model to ignore them is not a defence. CaMeL (Debenedetti et al. 2025) makes a system safe even when a model is tricked; on AgentDojo it completed 77% of tasks with provable security, against 84% with no defence. We use its core ideas: a quarantined reader, capability tags on every value, and policies checked before every tool call.

CaMeL also has a privileged planner that writes code from the user's request. We keep the planner but narrow it. A decision model picks one intent and its slots from closed lists, and code fills a fixed plan template. No model writes free-form plans or code, and the planner never sees supplier text. The bill pipeline itself is fixed code.

**Tags.** Sources: `owner`, `settings`, `registry`, `erp`, `computed`, `intent`, `supplier_doc`, `supplier_msg`, `market`. A derived value carries all its sources. A value is untrusted if any source is `supplier_doc`, `supplier_msg` or `market`. `intent` values come from the owner's or manager's request through the decision model: the source is trusted, but the reading can be wrong, so every intent with an external effect needs a confirmed preview (S9).

**Endorsement.** `bounded(x, erp_bound) = min(x, erp_bound)`, with `erp_bound` from ERP and settings only. Its result is tagged `computed:erp_bounded`. A supplier can make it smaller, never larger.

**Policies**

| ID | Rule |
| --- | --- |
| S1 | A payee comes only from `registry`. |
| S2 | A payment amount must carry `computed:erp_bounded`. A raw supplier amount never reaches `pay*`. |
| S3 | Untrusted values can only push a bill toward more scrutiny (T2, freeze, review). The one exception is the risk score, which decides T1. |
| S4 | Bank details from a supplier only open a "check by phone" task. The agent has no tool that changes a payee. |
| S5 | Every number on a card equals a tagged value. Supplier numbers are labelled "supplier says"; market numbers are labelled with their source and date. Untagged numbers block the card. |
| S6 | The explainer sees typed values and tags only (numbers, IDs, enums). Never raw supplier text. |
| S7 | Market values can raise a fair-price flag or appear on a card. They never set a payee or an amount. A PO draft's quantity comes from ERP needs and the owner's choice. |
| S8 | The intent router and the planner see the user's request and trusted state only. Never raw supplier text, supplier replies or market notes. |
| S9 | A plan is built only from catalogue templates. Every slot value comes from a closed list (registry, open bills, bundles, enums). A step with an external effect runs only after the user confirms the preview, and is checked again against S1–S7 when it runs. |
| S10 | Protective actions (hold, freeze, pause, probation, deduct a confirmed receivable) may run without approval, even when untrusted values trigger them, but only against the supplier those values came from. Undoing one needs the owner or the normal tier. |

**The S3 exception, stated openly.** The T1 decision depends on the reader's confidence, which comes from untrusted text. No policy removes that. Caps, cut-offs and (in reserve modes) the reserve cover it.

**Second layer.** The contract accepts only registered payees, within caps, once per bill, with a governor signature, even if someone bypasses the application.

**Extra layer.** The Jev injection flag sends supplier text that looks like instructions to T2 and the security log. It can only escalate, so an attacker who evades it gains nothing beyond what the other layers allow.

**Not stopped:** bad bills inside allowed flows, errors in our policies, an insider who fakes goods receipts in the ERP, side channels, compromise of both agent and governor keys, a request the user misreads and still confirms in the preview, and a supplier that trips holds or the circuit breaker to slow payments (bills fall back to people).

---

## 6. Checker

Deterministic Python.
1. **Supplier:** tax ID, bank details, fuzzy name, sender domain. A near-match domain goes to a person.
2. **Order:** invoice order number, else rank open orders. A tie goes to a person.
3. **Lines:** by item code, else description, unit and price, after unit conversion.
4. **Quantity:** billed now ≤ received − already billed.
5. **Price:** within the supplier's tolerance of the order price (e.g. ±1%).
6. **Tax and totals:** correct rate, lines add up, currency matches.
7. **Credits:** recorded returns, credit notes and open recoveries deducted.
8. **Duplicates:** exact and fuzzy (Fellegi–Sunter weights).
9. **Fair price:** for materials with a market index, the price change since the last purchase is compared with the index change (section 9.2).

Output: pass or mismatch with a reason, the margins to each tolerance (fed to the score), `erp_bound` for policy S2, and a proposed resolution for each mismatch (section 3.7). Matching cannot catch unrecorded events. Statement reconciliation finds some of them later; reserve modes cover the rest.

---

## 7. Contracts

### 7.1 Parameters

| Name | Real | Demo | Meaning |
| --- | --- | --- | --- |
| P-CAP | team sets | 5 tUSDC | Per-payment T1 cap, fixed across bundles |
| P-DAY, P-NDAY | per bundle | section 8.2 | Daily T1 amount and count caps |
| P-SUPWEEK | team sets | 5 tUSDC | T1 total per supplier in 7 days |
| r | per bundle | section 8.2 | Reserve per T1 payment, = K(β)/N (reserve modes) |
| P-WINDOW | 30 days | 5 min | Coverage window |
| P-DISPUTE | 5 business days | 2 min | Underwriter's dispute time (bonded mode) |
| P-COOL | 24 h | 5 min | Wait after a payee is added or changed |
| P-BREAK | 3 blocks in 10 min | same | Circuit breaker |

1 tUSDC stands for $1,000. The demo compresses time; K(β) and r use the real 30-day window.

### 7.2 PaymentVault

| Function | Caller | Rule |
| --- | --- | --- |
| `addPayee(id, wallet, rail)` | owner | Inactive until P-COOL ends. Rail = token or bank. |
| `freezePayee(id)` | owner, governor, agent | Immediate. Only the owner unfreezes. |
| `proposeSettings(...)` / `approveSettings(id)` | owner / underwriter | A bundle (mode, P-CAP, P-DAY, P-NDAY, P-SUPWEEK, r). Bonded bundles need both signatures; standard and self-reserve need the owner only. The agent can prepare the transaction from a SET-DIAL request; it cannot send it. |
| `payAutonomous(billId, supplierId, amount, settingsId, expiry, govSig)` | agent | Reverts unless: agent not paused; valid unexpired governor signature over these fields and the bill's input hash; payee active, not frozen; all caps hold; billId unused; in reserve modes, `BondPool.lock` succeeds. The reserve comes from the stored bundle, never the caller. Bank rail: records the payment and emits a bank reference. |
| `payApproved(billId, supplierId, amount, expiry, sig)` | agent | EIP-712 approver signature over bill, payee wallet, amount, expiry, with domain (chainId, vault). billId is the nonce. No reserve. |
| `recordOffset(billId, againstBillId, amount)` | agent | Records a recovery deducted from a later invoice of the same supplier. Amount ≤ the open receivable. |
| `pauseAgent()` / `unpauseAgent()` | owner, governor, agent / owner | Pause button, circuit breaker, and the agent pausing itself. |

### 7.3 BondPool (reserve modes)

| Function | Caller | Rule |
| --- | --- | --- |
| `fund` / `withdraw` | funder (company or underwriter) | Withdraw only if `balance − amount ≥ lockedTotal`. Below K, new locks fail and bills go to T2. |
| `lock(billId, amount, r)` | vault | Reverts unless `lockedTotal + r + amount ≤ balance` and not paused. |
| `release(billId)` | anyone | After P-WINDOW, no open claim. |
| `fileClaim(billId, loss, cause, evidence, sig)` | company (the agent submits it with the finance manager's EIP-712 signature) | Inside P-WINDOW. `loss ≤ paid`. Covered cause only. |
| `dispute` / `resolve(approvedLoss)` | underwriter / arbiter | Bonded mode. Disputed claims go to a separate arbiter key. |
| `executeClaim(billId)` | anyone | After an undisputed P-DISPUTE (immediate in self-reserve mode). Pays `min(loss, r_bill + free capital)` to the company treasury. |
| `recordRecovery(billId, amount)` | vault | Returns a recovered amount (offset or refund), up to the claim paid. |
| `pause` | funder, owner | Auto-pause when free capital < P-CAP. |

**Covered causes:** overpayment, duplicate payment or wrong payee on a T1 payment, from any source. T2 payments are not covered (a person approved them).
**Shortfall:** if free capital is not enough, the pool pays what it has, records the rest as owed, and pauses.

### 7.4 EvidenceAnchor
`anchor(day, merkleRoot)`, append-only.

### 7.5 Invariants (one test each)
B1 In reserve modes, no `payAutonomous` without a successful lock. · B2 `lockedTotal ≤ balance` always, also after claims. · B3 Free capital after a lock covers a total loss of that payment. · B4 Claims pay only the treasury, ≤ amount paid, once per bill. · B5 Recoveries ≤ amount owed. · B6 The agent key has no admin rights. · B7 No claim after the window; no release with an open claim. · B8 Only verified payees; no double payment; rule-breaking calls revert. · B9 No T1 without a valid governor signature. · B10 Bonded settings need owner and underwriter. · B11 Paused agent cannot pay. · B12 The locked reserve equals the stored r. · B13 The agent key can freeze and pause but cannot unfreeze, unpause or file a claim without the manager's signature.

### 7.6 Guarantees in plain words
1. **Average (all modes):** over all bills in a group, the expected share of bill value lost through autonomous payments is at most β (at most β × P-CAP per bill in dollars). For bills paid alone it is at most β ÷ T1 share. Needs new bills to resemble calibration bills.
2. **Exposure (all modes):** autonomous payments never exceed the caps, so the worst month is bounded by P-DAY × 30.
3. **Reserve (reserve modes):** each open T1 payment locks K(β)/N, so the contract holds K(β) for a full window. Claims in one window exceed K(β) with probability ≤ 1%, with 95% confidence, if errors are independent.
4. **Limit:** many failures at once can still exhaust a reserve. Then T1 stops and the caps limit exposure.
5. **Requests (all modes):** the correct reading of a request is among the readings the agent shows or asks about at least 95% of the time, if new requests resemble the calibration requests. A misread request can still only produce actions from the catalogue, under the same tiers and caps.

---

## 8. Risk core

### 8.1 Score and cut-off
- **Score** s ∈ [0, 1] (high = risky): logistic regression on lowest field confidence, check margins, fair-price excess, supplier record, novelty. Stretch: add the Jev review probability on typed facts (3.8).
- **Loss:** ℓ_i = loss_i / V_i ∈ [0, 1], from any covered cause. Calibration uses only bills with V ≤ P-CAP.
- **Cut-off (conformal risk control):** T1 if s ≤ λ_g, with
  `λ_g(β) = max { λ : ( Σ_i 1[s_i ≤ λ] ℓ_i + 1 ) / ( n_g + 1 ) ≤ β }`.
- **Data limit:** a group gets any T1 only if n_g ≥ 1/β − 1 (99 cases at 1%, 199 at 0.5%). The UI shows each group's smallest supported β.

### 8.2 Certified capital (reserve modes)

Conformal risk control bounds the average loss. A reserve also needs a bound on the bad case.

**Settings bundles.** Each dial position is (β, P-DAY, P-NDAY, r). Less autonomy means smaller caps, so N falls with β.

**Result.** K(β) such that `P(total claims on payments open in one window > K(β)) ≤ ε`, with confidence 1 − δ. K(β) against T1 share is an **Authority Frontier** in Chen's (2026) sense: authority released per unit of reserve capital. We also report his Capital@50 metric.

**Method.**
1. For each β on a grid of m values, compute the cut-offs λ_g(β).
2. For the calibration cases that would be T1: z = loss / P-CAP ∈ [0, 1].
3. Upper bounds μ̄ on the mean of z and ν̄ on the mean of z², with the Waudby-Smith–Ramdas betting bound, each at level δ/(2m).
4. The contract allows at most N = P-NDAY × 30 T1 payments in a window.
5. Bernstein's inequality:
   `K(β) = min( P-CAP × [ N μ̄ + sqrt(2 N ν̄ ln(1/ε)) + (2/3) ln(1/ε) ] , P-DAY × 30 )`
6. r(β) = K(β)/N. The funder deposits at least K(β) + P-CAP.

**Why pooling matters.** Chen bounds cumulative loss by summing per-action reserves, each covering its own action at level α/T (a union bound). That holds without independence, but any payment whose error probability is above α/T must reserve its full exposure, so capital approaches the maximum exposure. A Bernstein bound over independent payments grows as N μ + O(√N) instead.

**Illustration** (P-CAP = 5, ε = 1%, assumed μ̄ = ν̄; replace with calibration output):

| β | P-NDAY | P-DAY | N | μ̄ | K(β) | r | Max exposure |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0.5% | 3 | 10 | 90 | 0.003 | 24.6 | 0.27 | 300 |
| 1.0% | 5 | 15 | 150 | 0.006 | 34.2 | 0.23 | 450 |
| 1.5% | 8 | 20 | 240 | 0.010 | 50.9 | 0.21 | 600 |
| 2.0% | 10 | 25 | 300 | 0.015 | 70.0 | 0.23 | 750 |

K is about 8–9% of the maximum exposure. The (2/3) ln(1/ε) term sets a floor of about 3 × P-CAP when errors are rare.

**Assumptions (on the slide):** new bills resemble calibration bills; errors on different bills are independent; agent and governor keys are not both compromised.

**Correlated version (if time):** treat each supplier-week as one unit, using P-SUPWEEK, so one layout change counts once.

### 8.3 Other rules
- **Limit splitting:** if a supplier's 7-day T1 total plus this bill exceeds P-SUPWEEK, the bill goes to T2. The contract enforces the same cap (Chen's boundary-level aggregate retention, on-chain).
- **P-CAP stays fixed across bundles,** so a large budget cannot quietly reclassify large payments as routine.
- **Premium (bonded mode):** `1.2 × ê × V + r × ρ × 30/365`. Here ê is the estimated loss ratio for the bill's group and score bin, and ρ = 10% a year.
- **Drift guard:** `λ_g = λ_g^cal + d_g`, with `d_g ← min(0, d_g + η(β − ℓ_t))` after each known outcome. Nightly recalibration updates λ_g^cal only, so d_g persists. Set η so one typical error lowers λ_g by at least one score bin.
- **Probation:** after a confirmed error, the agent puts the supplier's next 5 bills on T2.
- **Self-recovery:** a confirmed overpayment becomes a receivable. The checker deducts it from the supplier's next invoice and the vault records the offset.
- **Planner:** pay early only if the discount's annual return `d/(1−d) × 365/(N−D)` (≈ 37% for 2/10 net 30) beats the credit rate and cash stays above the floor. Best returns first. A credit-line draw is T2. Nothing moves past its due date. The WHAT-IF intent uses the same planner as a simulation.

---

## 9. Market intelligence

The fair-price check (9.1–9.2) is core. Market watch (9.3) is built only after the request bar works end to end, and is the first cut.

### 9.1 Material map

One row per purchased material that has a public price series.

| Field | Example |
| --- | --- |
| Material | Copper rod |
| Price series | Copper, monthly, $ per tonne (World Bank Commodity Price Data) |
| Pass-through share s | Share of an index change that should reach the supplier's price. Estimated from the company's invoice history (regression of price changes on index changes), or set by the owner |
| Pricing lag L | Months between an index move and the supplier's price (e.g. 1) |
| Unit conversion | 1 t rod = 1 t copper |

Materials with no public series get no fair-price check and no market alert. The UI says so.

### 9.2 Fair-price check

For each invoice line of a mapped material whose unit price differs from the last price paid:
- Actual change: `a = p_invoice / p_last − 1`.
- Justified change: `j = s × (I_now / I_last − 1)`, with index values taken L months before each invoice date.
- Excess: `e = a − j`. Overcharge in dollars: `(p_invoice − p_last × (1 + j)) × quantity`.
- **Flag** if e is above the tolerance (e.g. 2 points) and above the 90% range of that supplier's past excess.
- **Action:** the bill goes to T2 with an evidence card (index chart, last price, justified price, invoice price, overcharge) and the proposed resolution "pay at the justified price, hold the excess". The agent drafts the query to the supplier and handles the reply (3.7).
- Under policy S3, market data can only push a bill to more scrutiny, never approve it.

**Example.** Copper rod was last paid at $11,200/t. The new invoice says $12,208/t (+9.0%). Copper rose 2.0% over the same lagged period, with pass-through 0.85, so the justified price is $11,390/t (+1.7%). The excess is 7.3 points. On 12 t that is $9,811 above the justified price. The bill is held and the query is drafted.

### 9.3 Market watch (price-range forecast)

**What we forecast.** The direction of traded prices is hard to forecast; for metals, research finds models often do not clearly beat a no-change forecast. Volatility is easier, because calm and turbulent periods cluster. So we forecast a **price range** and say when a large move has become more likely. We never claim the price will rise.

**Range.** A 90% range for the next 1 to 3 months, built with adaptive conformal inference around the no-change forecast, one model per series. Adaptive conformal keeps long-run coverage near 90% when a series changes behaviour; plain split conformal is not valid for time series.

**Alert signals** (market data only, thresholds from each series' own history, so no manual tuning):
1. Recent volatility in the top 10% of the series' history.
2. A CUSUM change-point detector fires on returns.
3. The 90% range is wider than the series' own 90th-percentile width.

An alert needs at least two of the three.

**Needs.** The quantity of each material for the next period comes from the ERP: production plan and open orders. This is a calculation, not a forecast.

**Suggestion.** For each alerted material the card compares three options: buy all now, buy half now, wait. For each it shows the cost at the low, middle and high end of the range, the storage cost, and the effect on cash. The suggested option has the lowest worst-10% average cost (CVaR), provided its expected extra cost stays within the owner's hedge budget (e.g. 1% of the purchase value) and cash stays above the floor. Otherwise it suggests "wait". When several materials alert, the cash check covers them together, using joint scenarios from historical periods.

**Example card.**
> Copper volatility is in the top 10% of its own history. Price now: $9,900/t. Next-month range (90%): $9,100–$10,700.
> You need 40 t in the next 2 months. Buying 20 t now costs $600 in storage, and cash stays above the floor.
> If the price reaches the top of the range, you save $15,400. If it falls to the bottom, you pay $16,600 more than waiting. At today's price it costs $600 more.
> Worst-case cost: $15,400 lower. Suggestion: buy 20 t now. [Buy 20 t] [Buy 40 t] [Wait]

**Action.** When the owner taps an option, or asks through the request bar (BUY-AHEAD), the agent drafts the purchase order in the ERP (T0 draft; a person posts it). The supplier's invoice then follows the normal flow. A large invoice is always T2.

---

## 10. Evidence and experiments

### 10.1 Scripted tasks (each ends in a hash or log line)

| # | Task | Evidence |
| --- | --- | --- |
| 1 | Routine bill paid alone; reserve locked, then released | Payment, release hashes |
| 2 | Same invoice as PDF and phone photo; second payment blocked | Log |
| 3 | Owner types "be more careful this month"; the agent shows the 0.5% bundle with its T1 share, caps, K and r; owner signs; new limits on-chain | Plan log, settings hashes |
| 4 | Agent reconciles the supplier statement, finds the missed credit, manager confirms → claim → payout → cut-off drops → probation | Case log, claim, payout hashes |
| 5 | Self-recovery: next invoice from that supplier is short-paid by the credit; recovery recorded | Payment, offset, recovery hashes |
| 6 | Bank-detail change by message; the agent freezes the supplier itself | Freeze hash (agent key) |
| 7 | Hidden instruction to pay a new account; Jev flags it, S1 blocks it | Policy log |
| 8 | Same poisoned invoice sent to a naive agent with no rules (separate demo vault): funds drained. Our agent: blocked | Drain hash, revert hash |
| 9 | Direct call from a non-agent key | Revert hash |
| 10 | Agent key with no governor signature (hacked server) | Revert hash |
| 11 | Pool too small → T1 reverts → approval card → paid | Revert, approval hashes |
| 12 | One large bill split into ten; T2; forced T1 hits P-SUPWEEK | Log, revert hash |
| 13 | 2/10 net 30 bill paid on day 9; another waits to its due date | Payment hash, log |
| 14 | Three blocked attempts → the agent pauses itself → owner unpauses | Pause, unpause hashes |
| 15 | Mainland payee via bank rail; vault records it | Record hash, bank reference |
| 16 | Fair price: copper rod +9% vs index +2%; bill held with "pay justified price, hold excess"; query sent with one tap; canned supplier reply classified "will issue credit note"; credit note recorded; bill paid at the justified price | Log, approved-payment hash |
| 17 | Market alert on replayed real copper prices; owner taps "Buy 20 t"; PO drafted; invoice paid after approval (only if market watch is built) | Log, approved-payment hash |
| 18 | Switch to standard mode; payments run with caps only; switch back | Settings hashes |
| 19 | Owner types "pay everything from Acme due this week except the disputed bill": plan preview, Run, three T1 payments and one T2 card | Plan log, payment hashes |
| 20 | Vague request "pay the copper supplier": two registered copper suppliers in the set → one question → answer → plan | Log with the conformal set |
| 21 | Owner cancels a running five-payment plan after two payments: the rest stop; log shows done and stopped steps | Payment hashes, log |

### 10.2 Data
- 2,000 events for a Hong Kong demo company over 12 months. Groups: routine 1,200, new supplier 300, price change 300, other 200. Half calibration, half test.
- Documents rendered from at least 8 layouts at normal scan quality, fixed before any reading and published in the repo. About 10% phone photos.
- Reader errors are measured on 200 labelled documents and feed the simulated error model. Process errors (unrecorded returns, off-order prices, missed duplicates, fraud) are simulated at stated rates, with a sensitivity run at double the rates.
- Supplier prices for mapped materials follow real index paths plus stated pass-through, with injected overcharges at a stated rate.
- Supplier statements for every supplier and month, with the missed credits from the process-error model.
- 100 owner requests for the catalogue plus UNSUPPORTED: 30 seeds written by the team, paraphrased by an LLM, every label checked by a person. Half calibration (the conformal sets), half test (the utility check in RED). One canned supplier reply (credit note) and one poisoned reply for RED.
- Market data: World Bank Commodity Price Data (monthly). Weekly or daily series if a free source is found.

### 10.3 Experiments

| ID | What it shows |
| --- | --- |
| AC-8 | Realised loss ratio ≤ β in every group over 100 splits; T1 share vs three baselines (person checks all, $5,000 rule, plain confidence threshold). Stretch: with and without the Jev score feature |
| CAPITAL | Per bundle: T1 share, K(β), Capital@50, share of windows where claims exceed K(β). Compared with Chen-style per-action union-bound reserves (main comparison) and naive rules (expected loss only, 10% of max exposure, no tail term) |
| FAIR | Detection rate and false flags on injected overcharges vs legitimate index-driven rises; dollars caught |
| RED | ≥ 12 attacks (invoice and email injection, fake bank change, direct call, no governor signature, limit splitting, look-alike domain, repeated attempts, poisoned market note, poisoned supplier reply, owner pastes a supplier email with an instruction into the request bar, request for an action outside the catalogue, …) under naive agent, policies only, policies + contract; plus utility on normal bills and normal requests |

**Charts:** naive vs our agent under attack; Authority Frontier (our K vs Chen-style reserves); T1 share vs β per policy; request → plan → hashes (one screenshot sequence); fair-price flags against the index; copper history with alerts and the 90% range (if market watch is built).

**Stated limits:** simulated company, error rates, delays, recovery rates and overcharges. Owner requests are paraphrases written for the test, not real users. Guarantees need new bills and requests to resemble calibration data. The capital bound assumes independent errors. Market watch forecasts ranges, not direction. The loss-ratio result in AC-8 checks the implementation; it is close to guaranteed when test and calibration data come from the same simulator.

---

## 11. Demo video (≤ 5 minutes)

| Time | Scene |
| --- | --- |
| 0:00–0:25 | **Split screen.** A poisoned invoice goes to a naive AI wallet: the money drains on the block explorer. The same invoice goes to our agent: Jev flags it, nothing moves, and the contract's refusal hash appears. |
| 0:25–0:50 | A crumpled invoice is photographed on a phone. The agent reads, matches and pays alone. The hash appears; the money counter ticks. |
| 0:50–1:35 | **The owner gives an order.** "Pay everything from Acme due this week except the disputed one." The plan appears, the owner taps Run, three hashes and one approval card follow. Then "pay the copper supplier": the agent asks which of two, the owner taps one. |
| 1:35–2:15 | **Fair price and the supplier query.** Copper rod +9% while copper rose 2%. The bill is held with "pay the justified price, hold $9,811". The query goes out with one tap; the supplier's reply comes back as a credit note; the bill is paid at the justified price. |
| 2:15–2:55 | **The agent finds and fixes its own mistake.** Statement reconciliation finds the missed $1,140 credit → manager confirms → claim repaid → next invoice short-paid → recovery on-chain → probation for that supplier. |
| 2:55–3:35 | **Risk dial.** The owner types "be more careful this month"; T1 share, caps and reserve change; the owner signs; new limits on-chain. Authority Frontier chart: our reserve vs Chen-style reserves. |
| 3:35–4:15 | **Security log.** Bank-detail change: the agent freezes the supplier itself. Hacked-server call reverted. Repeated attacks: the agent pauses itself. Actor column on every line. |
| 4:15–4:35 | **Market watch** (only if built): copper volatility alert with the 90% range; "Buy 20 t"; purchase order drafted. Otherwise the roadmap slide. |
| 4:35–5:00 | Results (attacks blocked, loss ratio vs β, reserve vs Chen-style reserves, overcharges caught) and stated limits. |

---

## 12. Prior work and our claim

| Work | Relevance |
| --- | --- |
| Chen 2026, Insuring Every Action | Deterministic runtime that prices each action against a reserve budget (conformal envelope) and bounds cumulative loss by summed per-action reserves (union bound, no independence needed). Signed capability tokens, aggregate retention against splitting, human approval for large money actions, Authority Frontier, Capital@k. No pooling across actions, no claims paid to the harmed party, no on-chain enforcement. Credential and executor compromise are out of its scope. |
| Hua et al. 2026, Quantifying Trust (ARS) | Settlement standard for agent jobs: fee escrow, underwriter premium with loading, optional provider collateral, claims, arbiter, payout vault, and a 2-of-3 release rule (agent plus human or underwriter). Pricing and capital are left open ("the bottleneck is risk modeling"); solvency is only simulated, and is negative with zero loading. |
| Hu and Chen 2025, Insured Agents | Insurers post stake for agents in exchange for premiums. Mechanism design. |
| Xu et al. 2026, Trace-Economic Underwriting | Prices agent risk from traces with deterministic loss labels. |
| Debenedetti et al. 2025, CaMeL | Capability-based defence against prompt injection, with a quarantined reader and a privileged planner. Our security layer follows it; our planner is narrower (closed lists and fixed templates). |
| Ren et al. 2023, KnowNo | Conformal prediction sets decide when an LLM planner should ask a person for help. Our clarification rule uses the same idea for owner requests. |
| TypeSafe AI 2026, Jev | Decision model with typed outputs and probabilities. Our intent router, reply classifier and injection flag. |
| CORA 2026 | Conformal risk control for GUI agents. No money. |
| AIUC-1 | Commercial standard, audits and insurance for agents, priced per audit. |

**How we fit.** Our security layer follows CaMeL. Our settlement flow follows ARS: a co-signing risk service, premium with loading, claims, arbiter, payout pool. Our runtime gate follows Chen. Our clarification rule follows KnowNo.

**Our claims:**
1. A complete payables agent where untrusted text can never choose a payee, raise an amount or change the steps, enforced twice (policies and contract) and measured against a naive agent.
2. A pooled, distribution-free bound on total claims in a window (betting confidence bounds plus Bernstein's inequality over independent payments, with N made finite by contract caps). We expect it to need roughly an order of magnitude less reserve than per-action union-bound reserves at the same 99% level; CAPITAL tests this.
3. An agent that takes requests in plain words and acts on them, where plans come from closed lists and fixed templates and clarifying questions come from conformal sets. A request can be misread, but never turned into an action outside the rules.
4. Market data used to act: fair-price holds with drafted supplier queries, and range forecasts with drafted buy-ahead orders, all under the same source-tag rules.

**Not claimed:** the first agent bond, the first per-action reserve, the Authority Frontier, price-direction forecasting, new language understanding, or new theory.

---

## 13. Team and schedule

| Stream | Owns | Done means |
| --- | --- | --- |
| A Chain | Contracts with modes, agent freeze and pause rights, claim signature, tests, deploy, executor, anchoring, bank rail, offsets, naive-agent demo vault, evidence file | Invariants pass (B1–B13); one script deploys, funds and sets the first bundle |
| B Risk | Data, document rendering, process errors, supplier statements, score, calibration, bundles, K(β), premium, drift, planner, conformal sets for requests, AC-8 and CAPITAL | `governor.decide()` returns tier, premium, reasons, signature; `capital.frontier()` returns K, r, T1 share per bundle; `intent.calibrate()` returns q̂ for intents and slots |
| C Agent | Intake, reader, checker incl. fair-price check (and FAIR), proposed resolutions, statement reconciliation, supplier query with one canned reply, protective actions, store, explainer, fraud guard, ERP adapter, policies (S1–S10), circuit breaker, self-recovery, plan execution tools | Document → matched bill → decision; every tool call passes the policy check; every intent template runs |
| D Product and requests | UI, request bar and plan view, intent catalogue, Jev integration and fallback, request data, deck, video. Then market watch: price data, material map, range model, alerts, suggestion | Demo runs from the UI with no terminal; a typed request runs end to end; market watch only if the request bar is done |

With three people, C also builds the UI, the catalogue shrinks to five intents (ASK-WHY, ASK-STATUS, PAY-SET, HOLD-SET, SET-DIAL), and market watch is cut.

**Freeze tonight:** schemas `Fact` (with tags), `Bill`, `Action`, `Decision`, `Bundle`, `Material`, `Intent`, `Plan`, `Step`; `governor.decide()`; `capital.frontier()`; `decide(schema, state)` (Jev or fallback); `intent.route(text, state)` (intent and slot sets with probabilities); `plan.build(intent)`; `plan.run(plan)`; `market.range(series)`; `executor.pay()`; log line `{ts, actor, kind, planId, inputHash, policy, decision, txHash}`.

**Fri 16 Oct, evening**
- [ ] Agree scope, stack, chain. Freeze interfaces. Repo, testnet funds, tUSDC.
- [ ] Email organisers: do testnet hashes count? Preferred chain?
- [ ] **Apply for Jev early access tonight.** Set up the fallback backend behind `decide()`.
- [ ] A: contract skeletons, first tests.
- [ ] B: demo company, templates, simulated error model; Chen-style reserve baseline.
- [ ] C: choose the reader; price and time the reads; run 5 degraded invoices end to end.
- [ ] D: intent catalogue and 30 seed requests; wireframes for the request bar and plan view; storyboard.

**Sat 17 Oct: components**
- [ ] A: vault and pool with modes done, agent freeze and pause, tests pass, deployed. Naive demo vault.
- [ ] B: score, cut-offs, bundles, first K(β); derivation checked by a second person; swap in real reader errors. 100 requests labelled; conformal sets for intents and slots.
- [ ] C: reader, checker, duplicates, fair-price check, accuracy; tags and policies S1–S10 in the pipeline; proposed resolutions; protective actions.
- [ ] D: UI shell on mock data; intent router on Jev or the fallback. **12:00: no Jev key → fallback, no more waiting.** Templates for PAY-SET, HOLD-SET, ASK-WHY, ASK-STATUS, SET-DIAL.
- [ ] 21:00 sync.

**Sun 18 Oct: integration**
- [ ] One document to an on-chain T1 payment with the reserve locked.
- [ ] One typed request to a preview, Run, and T1 payments with hashes.
- [ ] **12:00 go/no-go:**
  - If reader-to-payment fails, use clean JSON invoices and keep everything else.
  - If the request bar is not working end to end, keep ASK-WHY, PAY-SET and the clarifying question only.
  - If market watch has not started, cut it to the roadmap slide. Fair-price check stays.
  - Decide in 15 minutes.
- [ ] Claims, statement reconciliation, self-recovery, supplier query (one canned reply), dial with live K(β), fraud guard, circuit breaker, planner, fair-price cards, remaining intents.
- [ ] 20:00 feature freeze. Night: run all tasks once as a backup set.

**Mon 19 Oct: proof and package**
- [ ] 09:00–12:00: tasks again, hashes, experiments (AC-8, CAPITAL, FAIR, RED), charts.
- [ ] 12:00–15:00: technical document (B + D); security self-assessment (A + C).
- [ ] 15:00–19:00: video (section 11), deck, README.
- [ ] 20:00: dry run from a clean clone. **22:00: submit.**

---

## 14. Submission checklist

| Item | Content |
| --- | --- |
| Technical document | Architecture, request layer and plan templates, security layer, risk core with derivation, market intelligence, contracts |
| Deck | ≤ 10 min: problem, product, an agent you can instruct, safety by design, frontier, market intelligence, demo, results, compliance, roadmap |
| Demo video | ≤ 5 min, following section 11 |
| Source code | GitHub, README, deployment steps, tests, no secrets |
| Security self-assessment | Tiers T0, P, T1–T3 and their enforcement, policies S1–S10, RED results, Jev data handling, known risks |
| Execution evidence | All scripted tasks with hashes, time, action, actor, result, and how to check them, grouped into three story arcs (routine operations, mistake and recovery, attacks and defence) |

---

## 15. Risks

| Risk | Response |
| --- | --- |
| Integration late | Sunday 12:00 go/no-go |
| Scope too large for the team | Market watch is the first cut, then the request bar shrinks to three intents; the core never depends on either |
| No Jev access, or Jev down during the demo | Fallback backend behind the same interface; decide by Sat 12:00; the demo runs with either |
| A request is misread | Conformal sets trigger a question; nothing with an effect runs before the preview is confirmed; slots come from closed lists |
| Judges think it is not an agent | Requests → plans → actions on screen in the first 90 seconds; actor column on every log line |
| Reader too accurate | Report it; a high T1 share is a valid result. Do not retune the data |
| Reader inaccurate, late or costly | Review low-confidence fields; B runs on the simulated error model |
| Groups too small | Quotas in 10.2; a group below 1/β − 1 cases stays T2 |
| Bound too loose | Report it; show naive rules fail more often |
| Judges see it as Chen's work | Lead with pooling vs per-action reserves, backed by CAPITAL |
| Market alerts mostly false | Report the numbers; raise the threshold; never claim direction |
| Fair-price false flags | Supplier-specific excess range; report false flags in FAIR |
| Maths error | Second-person check, CAPITAL simulation |
| Testnet problems | Sunday backup set, local chain |
| "Insurance" or stablecoin concerns | Compliance words, testnet only, bank rail for mainland payees, standard mode needs no bank |
| Policies block normal bills or requests | Report utility; loosen only the blocking policy, never S1, S2 or S9 |

---

## 16. Judges' questions

| Question | Answer |
| --- | --- |
| Is this really an agent? | It takes requests in plain words, builds a visible plan, asks when unsure, and carries the plan out. It pays, holds, freezes, reconciles statements, queries suppliers and recovers its own mistakes. What it cannot do is let untrusted text pick a payee or an amount. |
| What stops prompt injection? | The reader cannot act; the planner never sees supplier text; policies check every value's source; the contract is a second layer. Task 8 shows a naive agent drained by the same invoice. |
| What if the agent misunderstands the owner? | If more than one reading is plausible, it asks. Nothing with an effect runs before the preview is confirmed, and every step still passes the normal checks and caps. |
| Why Jev and not an LLM? | The router only has to choose from closed lists. Jev returns a typed choice with probabilities in under a second and cannot return an option outside the list. The conformal sets do not depend on its calibration, and an LLM backend runs behind the same interface. |
| What stops the AI from inventing numbers? | The reader outputs a fixed schema only, a three-way match against order and goods receipt, no AI does maths, and every number on a card must trace to a source. |
| What if the agent server is hacked? | It still needs the governor's signature, a registered payee and the caps (task 10). |
| Does it need a bank? | No. Standard mode runs on prevention and caps alone. Self-reserve and bonded modes add a reserve sized by K(β). |
| Is this insurance? | No: a performance reserve on a testnet. The commercial path is a licensed insurer or bank guarantee. |
| How is this different from Chen? | Chen reserves each action on its own (union bound), which needs no independence but close to full collateral. We pool across payments and expect to need about a tenth of the reserve, at the price of an independence assumption that we stress-test. |
| How is this different from ARS? | ARS defines the settlement flow and leaves pricing and capital open. We fill that gap with a capital bound from data and enforce it on-chain. |
| Can you predict prices? | We forecast a range and say when a big move is more likely. We do not predict direction. |
| Why trust the fair-price check? | It uses a public index, the supplier's own price history and a stated pass-through share. It only holds a bill for a person; it never approves or cuts a payment alone. |
| Why a blockchain? | Nobody, including the agent and us, can change the caps, payees, signatures or claim rules. Hashes are public evidence. Settlement can still be a bank transfer. |
| Correlated errors? | Supplier-week cap, drift guard, probation, caps. The stress case is reported separately. |

---

## 17. Decisions at kickoff
- [ ] Stream owners and team size.
- [ ] Reader model and budget.
- [ ] Who applies for Jev access tonight; which fallback model.
- [ ] Final intent catalogue; α_I and α_S for the clarification sets.
- [ ] Testnet and UI framework.
- [ ] Demo values: P-CAP, P-SUPWEEK, bundle grid, windows, ε, δ, cash floor, credit rate, hedge budget, fair-price tolerance, process-error and overcharge rates, cost-per-invoice source.
- [ ] Demo materials and their price series.
- [ ] Who runs the governor and holds its key.

---

## Sources
- Angelopoulos et al. Conformal Risk Control. ICLR 2024.
- Angelopoulos, Bates. Conformal Prediction: A Gentle Introduction. Foundations and Trends in Machine Learning 2023.
- Ren et al. Robots That Ask For Help: Uncertainty Alignment for Large Language Model Planners (KnowNo). CoRL 2023.
- TypeSafe AI. Introducing System One Models & Jev. 15 Sep 2026. https://typesafe.ai/blog/introducing-system-one-models-and-jev
- Waudby-Smith, Ramdas. Estimating means of bounded random variables by betting. JRSS-B 2024.
- Boucheron, Lugosi, Massart. Concentration Inequalities. OUP 2013.
- Gibbs, Candès. Adaptive Conformal Inference Under Distribution Shift. NeurIPS 2021.
- Page. Continuous Inspection Schemes (CUSUM). Biometrika 1954.
- Rockafellar, Uryasev. Optimization of Conditional Value-at-Risk. Journal of Risk 2000.
- Díaz, Hansen, Cabrera. A random walk through the trees: Forecasting copper prices using decision learning methods. Resources Policy 2020.
- Chinn, Coibion. The Predictive Content of Commodity Futures. Journal of Futures Markets 2014.
- World Bank. Commodity Price Data (Pink Sheet).
- Chen. Insuring Every Action. arXiv 2605.25632, 2026.
- Hua et al. Quantifying Trust: Financial Risk Management for Trustworthy AI Agents (Agentic Risk Standard). arXiv 2604.03976v2, 2026.
- Hu, Chen. Insured Agents. arXiv 2512.08737, 2025 (preprint).
- Xu et al. Trace-Economic Underwriting. arXiv 2606.16465, 2026.
- CORA. arXiv 2604.09155, 2026.
- Debenedetti et al. Defeating Prompt Injections by Design (CaMeL). arXiv 2503.18813, 2025.
- Debenedetti et al. AgentDojo. NeurIPS 2024.
- Fellegi, Sunter. A Theory for Record Linkage. JASA 1969.
- AFP. 2026 Payments Fraud and Control Survey Report.
- AIUC. AIUC-1 standard.
