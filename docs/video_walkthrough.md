# Demo video plan (5 minutes)

This plan records one video of 5 minutes or less. The video shows each main feature once. Each scene gives:

- the time slot,
- who is signed in,
- the steps,
- the "real-world event" and the in-app control that stands in for it,
- the words for the voice-over.

The app has demo controls for events that a demo cannot wait for. Those controls are the scripts for the video.
They are listed in the table below. Use them on camera and say what they stand in for.

| Real-world event | Stand-in control in the app |
| --- | --- |
| A supplier sends a PDF invoice | Inbox → **Upload a bill** → a file from `data/demo/documents/` |
| A supplier sends an e-invoice | Inbox → **Process** next to the invoice |
| A supplier emails new bank details | Inbox → **Process** next to `lionrock_bank_change.eml` |
| A supplier replies to a query | Inbox → **Paste an email**, with `Subject: Re: Q-001` (not used in the 5-minute cut) |
| A supplier sends a monthly statement | Inbox → **Reconcile** next to `SHATINPCB-2025-12.csv` |
| The bank sends a statement | Payments → Bank transfers → **…with an unapproved debit** |
| Days go by | Settings → **Next day**, **Skip the payee cool-down** |
| The bank and the arbiter sign | Sign-in page → **Sign in with your wallet** → Local test account: bank / arbiter |

## 1. Prepare (30 minutes, before you record)

1. Start the app: `./run_local.sh`. Wait for "Starting Payables Desk API & Web App".
2. Create the demo sign-ins (one time; safe to run again): `.venv/bin/python scripts/demo_accounts.py`

   | Person | Email | Password | Signs on-chain as |
   | --- | --- | --- | --- |
   | Owner | `demo.owner@harbour-demo.test` | `Harbour-Demo-Desk-2026` | Owner (`0xf39F…2266`) |
   | Finance manager | `demo.finance@harbour-demo.test` | `Harbour-Demo-Desk-2026` | Finance manager (`0x90F7…b906`) |
   | Bank | Sign-in page → **Sign in with your wallet** → Local test account: bank | no password | Bank |
   | Arbiter | Sign-in page → **Sign in with your wallet** → Local test account: arbiter | no password | Arbiter |

   Both email accounts are in the company "Harbour Precision Demo". The script links their wallets already.
3. Open <http://127.0.0.1:8000/login> in two browser profiles: the owner in profile A, the finance manager in
   profile B.
4. Open a private window for the bank and the arbiter.
5. Open Odoo (<https://iut-dhonghorsho.odoo.com>) in a tab. Go to **Purchase → Orders**.
6. Open the AgentMail console for `fin-suppliers@agentmail.to` in a tab. Supplier mail from the agent arrives there.
7. Do a full practice run. Then reset: Settings → **Start the demo again** → **Yes, start again**. Then click
   **Skip the payee cool-down**.
8. Set the screen to 1080p, the browser zoom to 110–125 %, and turn notifications off.

Note: Gemini (free tier) can take 10–30 s for one answer. Record each scene as a separate clip. Cut the waits
in editing. The video uses Gemini two times only: the two PDF uploads in scenes 2 and 3.

## 2. Scenes

### Scene 1 — The problem (0:00–0:20)

Show: the landing page at `/`.

Voice-over: "Companies want AI agents to pay their bills. But an agent that reads supplier documents can also take
orders from them. One hidden line in an invoice can send the money to a criminal. We built an agent that pays
routine bills alone, and no text it reads can change who gets paid."

### Scene 2 — A routine bill, from Odoo to payment (0:20–1:10)

Who: owner (profile A).

1. Show the Odoo tab: the Kai Tak Fasteners purchase order and its receipt.
2. Go to the desk. Click **Inbox → Upload a bill**. Choose `data/demo/documents/t01_routine.pdf`.
3. Show the reader panel: the page, each field, the confidence, and the decision.
4. Show the bill: **Paid**, "Paid by: Agent", and the table **Invoice vs order vs goods received**.
5. Click **Verify** next to the payment. Show the on-chain confirmation.
6. Show the Odoo tab: **Accounting → Payments**. The memo holds the transaction hash.

Stand-in: the upload stands in for a supplier invoice that arrives by email.

Voice-over: "The purchase order and the goods receipt come live from Odoo. The AI reads the PDF into fixed fields
only. Then nine fixed checks compare the bill with the order and the receipt. The risk is low, so the agent pays
alone from a smart-contract vault. The payment goes back into Odoo with its transaction hash."

### Scene 3 — The poisoned invoice (1:10–1:50)

Who: owner.

1. Click **Inbox → Upload a bill**. Choose `data/demo/documents/t07_poisoned.pdf`.
2. Show the reader panel: the hidden instruction appears as plain text. The decision is **held**.
3. Go to **Controls**. Show the security event and the frozen payee.

Stand-in: the PDF stands in for a fraudulent invoice with an instruction in small grey print.

Voice-over: "This invoice hides an order: send the full balance to another wallet. The reader shows the text but
cannot act on it. The payee does not match the registry, so the agent holds the bill and freezes the payee. If
someone forces a payment, the smart contract refuses it."

### Scene 4 — A padded bill and two signatures (1:50–2:40)

Who: owner, then finance manager (profile B), then owner.

1. Owner: **Inbox → Process** next to `ACM-2512412`. The bill needs approval.
2. Show **Market check**: copper rod +9.0 %, the World Bank index justifies +0.6 %, $4,160.48 over the market.
3. Show the AgentMail tab: the query Q-001 that the agent sent to the supplier.
4. Finance manager: **Approvals** → the bill → **Approve and sign**. The wallet signs.
5. Owner: **Approvals** → sign the second signature. Show **Payments** and the "Paid by" column.

Stand-in: the sandbox inbox stands in for the supplier's real address.

Voice-over: "Copper went up less than one percent, but the supplier raised the price by nine percent. The agent
uses real World Bank prices to find the fair price. It holds the excess and emails the supplier itself. Above the
limit, a person must sign in their own wallet. Above twenty-five thousand dollars, the owner signs too."

### Scene 5 — A fake bank-detail change (2:40–3:15)

Who: finance manager, then owner.

1. Finance manager: **Inbox → Process** next to `lionrock_bank_change.eml`.
2. Show the message: "Payments to this supplier are frozen and the real supplier has been warned."
3. Show **Inbox → Outbox**: the bank-change warning.
4. Owner: **Suppliers → Lion Rock → Change payment details**. Fill in the call-back number from the records, and
   who confirmed. Click **Sign the change**, then **Unfreeze**. Show "Cool-down".

Stand-in: the `.eml` file stands in for an email from a look-alike address.

Voice-over: "Most payment fraud starts with one email: 'we changed our bank.' The agent never accepts new bank
details from an email. It freezes the supplier and warns the real one. Only the owner can change the details,
after a call to the number in our own records. Then a cool-down starts before the first payment."

### Scene 6 — A request in plain words (3:15–3:45)

Who: owner.

1. Type in **Ask the agent**: "Pay the copper supplier".
2. The agent asks one question: "Which supplier?" Choose **Acme Metals (HK) Ltd**.
3. Show the plan. Click **Run**. Show "Done."

Voice-over: "You can give the agent orders in plain words. When a request has two readings, it asks one question.
It shows a plan first. Nothing runs until a person clicks Run."

### Scene 7 — The bond pays back a mistake (3:45–4:25)

Who: finance manager, bank, arbiter, finance manager.

1. Finance manager: **Inbox → Process** next to `SHA-2512015`. Then **Reconcile** next to `SHATINPCB-2025-12.csv`.
2. **Disputes** → the missed credit → **Confirm and sign**.
3. Bank (private window, wallet sign-in): **Bank → Dispute**.
4. Arbiter (wallet sign-in): **Bank** → enter the amount → **Decide**.
5. Finance manager: **Disputes → Pay out the claim**. Show "Paid to the company".

Stand-in: the CSV stands in for the supplier's monthly statement. The test wallets stand in for a partner bank
and an independent arbiter.

Voice-over: "When the agent makes a mistake, a bond pays the company back. Here the supplier's statement shows a
credit that the agent missed. The bank can dispute the claim, and an arbiter decides. The bond pays out on-chain."

### Scene 8 — Risk and records (4:25–5:00)

Who: owner, then bank.

1. **Risk and reserve** → **Careful** → **Switch on-chain**.
2. Bank: **Bank → Approve from my wallet**.
3. Owner: **Payments → Bank transfers → Make payment file**, then **…with an unapproved debit**. Show the alert.
4. **Activity**: the journal and the on-chain anchor.

Stand-in: the button stands in for the bank's statement file (camt.053).

Voice-over: "The owner chooses how much risk the agent may take alone. The bank approves it, because the bank
holds the bond. Payments also leave as standard bank files, and a debit that nobody approved raises an alert.
Every action goes into a journal that is anchored on-chain. Thank you."

## 3. Edit

1. Cut every wait for Gemini, a wallet signature or a page load.
2. Put a title card of 2 seconds before each scene.
3. Check the total time. If it is more than 5:00, cut scene 8 step 3 first, then scene 6.
4. End on one card: the GitHub link, the Base Sepolia contract links from the README, and the team names.

## 4. If something fails during recording

| Problem | Do this |
| --- | --- |
| The PDF upload waits more than 30 s | Use **Process** next to the same invoice in the Inbox. It needs no AI. |
| The request box gives an error | The rule router answers. Record again, or keep the rule-router answer. |
| A signature fails | Check that the profile has its wallet linked (Settings → My account). |
| The state is wrong | Settings → **Start the demo again**, then **Skip the payee cool-down**. |
