# The Insured Agent: build plan

**Hackathon:** Topic F, Agent Wallet. Theme: AI as a Financial Participant.
**Submit by:** Mon 19 Oct, 22:00 (Dhaka), one day before the 20 Oct deadline. Confirm the organisers' deadline time zone today.
**Plan date:** Fri 16 Oct 2026.

> An AI payables clerk that proves how much it may lose, puts that money up before it acts, and repays you when it's wrong.

---

## 1. What we are building

The agent reads supplier documents, checks and matches them, and pays suppliers on-chain. Before any payment it makes alone (T1), it quotes its own risk and locks a reserve from an underwriting pool. If the pool cannot cover the reserve, the contract refuses and the payment becomes a T2 approval card. If a T1 payment later proves wrong, a claim repays the company from the pool, and the agent's cut-off tightens.

WeBank plays the underwriter: it funds the pool and earns a premium priced from the agent's risk record.

**Two guarantees, both enforced**
- Average: conformal risk control keeps expected loss per autonomous action ≤ α (the owner's budget).
- Worst case: total claimable autonomous loss ≤ the funded pool, enforced by the contract.

### In scope
- Job 1 Read and record: inbox (email + photo + WhatsApp as files), reader, checks, ERP/spreadsheet writer, supplier memory (basic).
- Job 2 Check and chase: confirmation check, three-way match, duplicate catcher. Chaser = templates only.
- Job 3 Pay right: payment-date planner (discount vs due date vs cash floor), payments within limits, fraud guard, escrow for new suppliers (if time), evidence log.
- **The bond:** reserve quote, lock, release, claim, reprice, premium.
- Risk dial with conformal calibration, one cut-off per group, drift guard.

### Out of scope (roadmap slide only)
Market scene (Job 4: copper, buy-ahead, CVaR), new-supplier search, quarterly review, sell side, supplier-side agent, FATE, cross-chain, Peppol, negotiation, a real licensed insurance policy.

### Compliance framing (use these words everywhere)
- "Performance reserve" or "loss bond", never "insurance policy". Insurance is the commercial path, not what we run.
- Testnet only, mock stablecoin (tUSDC). Payees in mainland China and Bangladesh are blocked from the on-chain rail; the bank-transfer fallback is shown.
- The agent never holds keys that can fund, withdraw, add payees or change caps.

---

## 2. Architecture

| ID | Component | Owner stream | Notes |
| --- | --- | --- | --- |
| C1 | Connectors | C | Folder of sample emails, photos, WhatsApp exports, CSV "ERP" |
| C2 | Reader (quarantined VLM/LLM) | C | No tools, no keys. Returns typed fields + confidence. Two independent readings for the agreement feature |
| C3 | Checker | C | Arithmetic, units, tax, three-way match, duplicates. Deterministic |
| C4 | Model store | C | SQLite. Fact records with source and as-of |
| C5 | Planner (privileged LLM) | C | Sees typed values only. Writes explanations; grounding check rejects any uncalculated number |
| C6 | Solvers | B | Payment-date planner (small LP or greedy), risk score |
| C7 | Governor | B | Score → group cut-off λ_g → T1 or T2. Reserve quote. Drift guard |
| C8 | Executor | A | Builds and submits transactions |
| C9 | Signer + contracts | A | `PaymentVault`, `BondPool`, `EvidenceAnchor` |
| C10 | Evidence log | A | Append-only JSONL, daily Merkle root anchored on-chain |
| C11 | Views | D | Inbox, bills, approval cards, risk dial, bond panel, weekly brief |

**Stack (proposed, confirm at kickoff):** Python 3.11 + FastAPI; SQLite; Foundry + Solidity 0.8; web3.py; React (Vite) or Streamlit for the UI; an EVM testnet (Sepolia or Base Sepolia). The contracts are plain Solidity, so they can be redeployed on FISCO BCOS later for the WeBank story.

---

## 3. Contract spec

### PaymentVault
| Function | Who may call | Rule |
| --- | --- | --- |
| `addPayee(supplierId, addr)` | owner | Starts a cooldown (demo: 5 min). Payee inactive until it ends |
| `freezePayee(supplierId)` | owner or governor key | Immediate. Unfreeze is owner only |
| `setCaps(perPaymentCap, dailyCap)` | owner | Agent key cannot call |
| `payAutonomous(billId, supplierId, amount, reserve)` | agent key | Reverts unless: payee active and not frozen; amount ≤ cap; daily cap holds; billId unused; `BondPool.lock(billId, reserve)` succeeds |
| `payApproved(billId, supplierId, amount, approvalSig)` | agent key | Needs a valid approver signature over (billId, supplier, amount, expiry). No reserve |
| `escrowFund / escrowRelease / escrowRefund` | agent key / receiver role / owner | Only if time allows |

### BondPool
| Function | Who may call | Rule |
| --- | --- | --- |
| `fund(amount)` | underwriter (WeBank role) | Adds capital |
| `lock(billId, reserve)` | vault only | Reverts if `lockedTotal + reserve > balance` or pool paused |
| `release(billId)` | anyone | Only after the settlement window (demo: 2 min) and no open claim |
| `fileClaim(billId, loss, evidenceHash)` | checker key or FM | `loss ≤ paid amount`. Window must still be open |
| `approveClaim(billId)` | arbiter (WeBank role) | Pays `loss` to the company treasury, never anywhere else |
| `payPremium(amount)` | company treasury | Moves premium to the underwriter |
| `pause / unpause` | underwriter or owner | Auto-pause when free capital < minimum |

### EvidenceAnchor
`anchor(day, merkleRoot)`, owner or agent key, append-only.

### Contract invariants (each gets a Foundry test)
- B1 No `payAutonomous` succeeds without a successful `lock`.
- B2 `lockedTotal ≤ balance` at all times.
- B3 A claim never exceeds the paid amount and pays only the treasury.
- B4 Total claims paid ≤ total funded capital.
- B5 The agent key cannot fund, withdraw, add payees, unfreeze or change caps.
- I1 / I8 / I15 from the formal spec: verified payees only, no double payment, any direct call that breaks a rule reverts.

---

## 4. Risk core (stream B)

**Score** `s(a)` in [0,1]: logistic regression on five features: lowest field confidence, check margins, supplier tier and record, novelty, agreement between two readings.

**Groups:** routine bill, new supplier, price change, other. `P-CAL-MIN = 100` labelled cases before a group gets T1.

**Cut-off** (conformal risk control, Angelopoulos et al. 2024):
`λ_g = max { λ : (Σ_i 1[s_i ≤ λ] · c_i / CAP + 1) / (n_g + 1) ≤ α }`, with `α = B / (1000 × CAP)`.

**Reserve quote:** `reserve(a) = V(a) × p_up(g, bin(s(a)))`, where `p_up` is the 95% upper bound of the observed error rate in that score bin on calibration data. Floor of 0.5% of V so no T1 payment locks zero.

**Drift guard** (Gibbs & Candès 2021): `λ_g ← λ_g + η (α − loss_t)` after each labelled outcome; a paid claim counts as a loss. `η = 0.01`. Full recalibration nightly in the demo.

**Premium (weekly):** `premium = Σ reserves locked that week × (1 + loading)`. Loading starts at 20%, falls 2 points per clean week, rises 10 points per paid claim. State it as a demo pricing rule, not an actuarial model.

**Limit splitting (EC-SE4):** reserves aggregate per (supplier × 7-day window). The quote uses the aggregate exposure, after Chen (2026).

---

## 5. Workstreams

Team size assumed to be four. With fewer people, merge D into C and B.

| Stream | Owns | Done means |
| --- | --- | --- |
| **A Chain** | Contracts, Foundry tests, deploy scripts, executor, evidence anchoring | All B and I tests green on testnet; one script deploys and funds everything |
| **B Risk** | Synthetic company + 2,000 events, score model, calibration, reserve quote, drift guard, payment-date planner, experiments | `governor.decide(action)` returns tier, reserve and reasons; AC-8 and AC-9 charts |
| **C Agent** | Intake, reader, checker, matcher, model store, planner explanations + grounding check, fraud guard | A document goes from folder to a matched bill with a governor decision; AC-1 measured |
| **D Product** | UI, approval cards, risk dial, bond panel, weekly brief, deck, video, README, evidence file | Demo script runs from the UI with no terminal |

### Interfaces to freeze tonight
- `Fact`, `Bill`, `Action` and `Decision` JSON schemas (from the formal spec, section 3).
- `governor.decide(Action) -> {tier, score, cutoff, reserve, reasons[]}`.
- `executor.pay(Decision) -> {status, txHash | revertHash}`.
- Evidence log line: `{ts, actor, kind, inputHash, decision, txHash}`.

---

## 6. Schedule (Dhaka time)

### Fri 16 Oct, from 17:00: kickoff
- [ ] Agree scope, stack, chain and the compliance wording (section 1).
- [ ] Repo, branch rules, `.env` template, testnet faucet funds, mock tUSDC.
- [ ] Freeze the interfaces in section 5.
- [ ] B: define the demo company (suppliers, materials, POs, 12 months) and error rates.
- [ ] A: contract skeletons and the first Foundry tests.
- [ ] C: pick the reader model; read 5 sample invoices end to end.
- [ ] D: UI wireframe for the six views; demo storyboard.

### Sat 17 Oct: components
- [ ] A: `PaymentVault` + `BondPool` complete, B1–B5 tests green, deployed to testnet.
- [ ] B: 2,000 events generated and rendered as images; score model trained; first λ_g per group.
- [ ] C: reader + checker + three-way match + duplicate catcher on the rendered set; field accuracy measured.
- [ ] D: UI shell wired to mock data: inbox, bill, approval card, risk dial, bond panel.
- [ ] 21:00 sync: every stream demos its piece in isolation.

### Sun 18 Oct: integration
- [ ] One document flows to an on-chain payment with a locked reserve (task 3).
- [ ] Claim flow end to end: misread → claim filed → approved → treasury repaid → λ tightens (task 5).
- [ ] Risk dial changes α, recalibrates, and the UI shows the new T1 share, reserve and premium.
- [ ] Fraud guard: bank-detail freeze, injection ignored, direct-call revert.
- [ ] **18:00 go/no-go.** If the reader or the vault does not work end to end, cut to Job 3 only: invoices arrive as clean JSON, keep the bond, fraud guard and planner. Decide in 15 minutes and do not revisit.
- [ ] 22:00 feature freeze for new features. Bugs only after this.

### Mon 19 Oct: proof and package
- [ ] Morning: run all 10 scripted tasks; collect hashes and logs into `evidence/`.
- [ ] Run the experiments (section 8) and make the charts.
- [ ] Red-team run: at least 8 attacks, with and without defences.
- [ ] Afternoon: record the video (follow the storyboard); finish the deck and README.
- [ ] 20:00 dry run of the full submission from a clean clone.
- [ ] **22:00 submit.** Tue 20 Oct is buffer only.

---

## 7. Scripted tasks (evidence file)

Every task ends in a transaction hash or a log line. Topic F scores task completion by hashes.

| # | Task | Evidence |
| --- | --- | --- |
| 1 | Onboarding: agent writes the business brief, owner approves it, rules and caps are set on-chain | `setCaps` hash + log |
| 2 | Same invoice by email and as a paper photo becomes one bill | Log |
| 3 | Routine matched bill paid alone: reserve locked, payment sent, reserve released after the window | `lock`/pay hash + `release` hash |
| 4 | Owner turns the risk dial from $200 to $50 per 1,000; T1 share, reserve and premium change | Log + `payPremium` hash |
| 5 | Supplier changes invoice layout; agent overpays; claim filed and approved; treasury repaid; λ tightens | `fileClaim` + `approveClaim` hashes |
| 6 | Bank-detail change arrives by WhatsApp; supplier frozen until callback | `freezePayee` hash |
| 7 | Invoice carries a hidden instruction; agent ignores and logs it | Log |
| 8 | Raw transaction that skips the agent | Revert hash |
| 9 | Reserve does not fit the pool; autonomous call reverts; T2 card approved; paid | Revert hash + `payApproved` hash |
| 10 | Ten small bills split from one large one; aggregate reserve sends them to T2 | Log + revert hash |

---

## 8. Experiments (the numbers judges see)

| ID | Result | Setup | Owner |
| --- | --- | --- | --- |
| AC-1 | Field accuracy ≥ 95% on 50 labelled documents; every miss caught by a check or sent to review | Labelled subset of the rendered set | C |
| AC-8 | Mean realised loss ≤ α in every group over 100 random splits; T1 share vs three baselines (human checks all, fixed $5,000 rule, plain confidence threshold) | 2,000 simulated events | B |
| AC-9 | Drift guard brings weekly loss back under α after a supplier layout change | Simulated layout change | B |
| BOND | Over 100 splits: realised autonomous loss vs reserves locked vs pool. Total loss never exceeds the pool | Same events, replayed through the contracts on a local chain | A + B |
| RED | Attack success rate with and without defences: injection, fake bank change, direct call, limit splitting, look-alike domain (≥ 8 attacks) | Red-team script | C + A |

**Main chart:** share handled alone vs risk budget, one line per policy. Label it an Authority Frontier and cite Chen (2026), arXiv 2605.25632.

**Stated limits:** simulated data; the conformal guarantee is on average and needs new cases to resemble calibration cases; no peer review.

---

## 9. Deliverables checklist
- [ ] Public repo with README: one-liner, architecture diagram, how to run, contract addresses, limits.
- [ ] `evidence/`: one folder per scripted task with hashes, logs and screenshots.
- [ ] Deck (≤ 12 slides): problem, the insured agent, how it works, demo, results (AC-1, AC-8, BOND, RED), compliance, WeBank role, roadmap, sources.
- [ ] Demo video (check the length limit in the rules), ending on the claim scene.
- [ ] Technical document: the formal spec updated with the bond (section 3 here) and the experiments.
- [ ] Sources cited: Angelopoulos et al. 2024 (CRC); Gibbs & Candès 2021 (ACI); Chen 2026 (arXiv 2605.25632); Insured Agents, AAMAS 2026 (arXiv 2512.08737); trace-economic underwriting (arXiv 2606.16465); CORA; AIUC-1.

---

## 10. Risks

| Risk | Effect | Response |
| --- | --- | --- |
| Integration slips past Sunday | Unfinished tasks lose the 40% task score | 18:00 Sunday go/no-go cut rule (section 6) |
| Reader accuracy below 95% | AC-1 fails | Route low-confidence fields to review; report the review rate honestly |
| Calibration groups too small | No T1 in some groups | Generate more events for those groups; a group with < 100 cases stays T2 and we say so |
| Testnet congestion or faucet limits on Monday | Missing hashes | Run all scripted tasks Sunday night as a backup set; keep a local-chain fallback |
| Judges read "insurance" as unlicensed activity | Compliance points lost | Use the section 1 wording; testnet only |
| Judges think the frontier chart is copied | Lower innovation score | Cite Chen; stress on-chain enforcement and claims as our addition |

---

## 11. Decisions to make at kickoff
- [ ] Stream owners (A, B, C, D).
- [ ] Testnet: Sepolia or Base Sepolia. FISCO BCOS only if A finishes early on Sunday.
- [ ] Reader model and its budget.
- [ ] UI: React or Streamlit.
- [ ] Demo values: payment cap, pool size, settlement window, starting α.
- [ ] Whether escrow for new suppliers is in or out.
