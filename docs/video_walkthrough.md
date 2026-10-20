# Recording the demo video

A path through every feature on the desk, in five short clips. Each clip says who to be, what to click, and what
the viewer should see. For a full check of every case, see `manual_testing.md`; this file is only the recording path.

## Before you record (10 minutes)

1. Restart the stack so it has the latest code and the Odoo records: stop `./run_local.sh` (Ctrl+C), then run it
   again. Open http://127.0.0.1:8000.
2. Two browser profiles, side by side: **owner** in one, **finance manager** in the other. Both signed in with
   email, both with a linked wallet (**Settings → My account → Link a wallet → Local test account**).
3. A third private window for the **bank** and the **arbiter** (they use **Sign in with your wallet**).
4. In a fourth tab, open Odoo (https://iut-dhonghorsho.odoo.com) on **Purchase → Orders**, then **Accounting →
   Payments**.
5. Do one dry run of clip 2, then reset: **Settings → Start the demo again → Yes, start again**, and **Skip the payee cool-down**. Odoo payments posted by the agent are
   removed by the reset too.
6. Screen: 1080p, browser zoom 110–125 %, notifications off.

The vision reader (PDFs and photos) and the request box use Gemini on the free tier: an answer can take 10–30 s.
Process the sample invoices from the **Inbox** (they are e-invoices and need no model). Upload one PDF only in
clip 2, and cut the wait in editing.

## Clip 1: sign-in and the team (owner, about 45 s)

| Do | The viewer sees |
| --- | --- |
| Landing page at `/` → **Open the desk** → sign in with email | The desk opens on **Bills** |
| **Settings → Team** | Owner and finance manager with their roles and wallets; the on-chain signers table |
| **Settings → My account** | Two-step sign-in and the linked signing wallet |

## Clip 2: a routine bill paid by the agent, from Odoo (owner, about 90 s)

| Do | The viewer sees |
| --- | --- |
| Odoo tab: **Purchase → Orders**, open the Kai Tak Fasteners order | The order and its goods receipt, in Odoo |
| Desk: **Inbox → Upload a bill** → a sample PDF (or **Process** next to `KAI-2512001`) | "What the reader sees": the page, each field with its confidence, then the decision |
| The bill opens | **Paid**, "Paid by: Agent"; **Invoice vs order vs goods received** matches Odoo's numbers; the checks list |
| **Verify** next to the payment in "What happened" | The transaction confirmed on-chain |
| Odoo tab: **Accounting → Payments** | A new payment, its memo holds the transaction hash |

## Clip 3: the attacks it stops (owner, about 90 s)

| Do | The viewer sees |
| --- | --- |
| **Inbox → Process** next to `TSU-2512019` (poisoned invoice) | Held; the hidden instruction is shown as text; the payee is frozen |
| **Inbox → Process** next to `lionrock_bank_change.eml` | "Payments to this supplier are frozen and the real supplier has been warned" |
| **Inbox → Outbox** | The bank-change warning the agent sent |
| **Controls** | The rules, the chain limits, frozen payees, and the security events from the two steps above |

## Clip 4: a padded bill and two signatures (finance manager, then owner, about 90 s)

| Do | The viewer sees |
| --- | --- |
| Owner: **Inbox → Process** next to `ACM-2512412` | **Needs approval**: copper rod +9.0 % while the World Bank index justifies +0.6 % |
| Finance manager: **Approvals** → the bill | **Market check**: $4,160.48 over the market; the query the agent sent (Q-001) |
| **Approve and sign** (wallet) | "The owner signs too" (above the two-signature threshold) |
| Owner: **Approvals** → sign | Paid; **Payments** shows "Paid by" for each payment |

## Clip 5: plain-words request, risk and the bond (about 90 s)

| Do | The viewer sees |
| --- | --- |
| Owner: **Ask the agent**: "Pay the copper supplier" | One question ("Which supplier?"), then a plan; nothing runs before **Run** |
| **Run** | "Done." and the payments |
| **Risk and reserve** → choose **Careful** → switch on-chain | Waiting for the bank |
| Bank window: **Bank → Approve from my wallet** | The setting is active; the reserve, locks and premiums |
| **Activity** | The journal: every action, who did it, the on-chain anchor |

## Joining the clips

Cut the waits for a model or a wallet signature. Put a title card before each clip ("The routine bill", "The
attacks", ...). End on the Odoo payment and the Basescan-verified contracts (README links).
