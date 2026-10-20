# What is real and what is simulated

The submission runs real software against real services where a hackathon can reach them, and says plainly where
it cannot. "Simulated" here means the part works as described but stands in for something only a real company, bank
or regulator can provide.

## Real

| Part | What it is | Where to check |
| --- | --- | --- |
| Smart contracts | `PaymentVault`, `BondPool`, `EvidenceAnchor`, deployed and source-verified on Base Sepolia | `chain/deployments/baseSepolia.json`, sepolia.basescan.org |
| Public evidence | The scripted tasks run on Base Sepolia; every step links its transaction | `evidence/evidence_baseSepolia.md` |
| Public anchors | Every company's journal head, hourly, one Merkle root on Base Sepolia | Activity page, `public_anchor.py` |
| FISCO BCOS | The same contracts and tasks on a local four-node FISCO BCOS v3 chain | `evidence/evidence_fisco.md`, `chain/fisco/` |
| Database | Neon Postgres: rows per company, append-only hash-chained journal | `store.py` |
| Sign-in | Email and password, two-step sign-in, companies, roles, invitations (Better Auth) | `auth/`, `identity.py` |
| Email | The agent's own inbox at AgentMail (`fin-agent@agentmail.to`): it sends and reads real mail | `mail.py` |
| Reading invoices and requests | Google Gemini (gemini-3.6-flash) reads PDFs and photos and routes requests | `reader.py`, `intent/` |
| Market prices | World Bank Commodity Price Data (monthly) | `data/market/` |
| Exchange rates | European Central Bank reference rates for the invoice date (Frankfurter service), source on each bill | `fx.py` |
| Sanctions list | US Treasury OFAC SDN list, names and aliases | `data/sanctions/`, `sanctions.py` |
| Bank file formats | ISO 20022 pain.001.001.09 (payments out) and camt.053.001.08 (statements in) | `bankfiles.py` |
| ERP connector | Odoo 17 through its external API (tested against a local Odoo) | `apagent/erp/odoo.py` |
| Research methods | Conformal risk control, KnowNo sets, betting-bound capital, adaptive conformal ranges, Fellegi–Sunter duplicates | `apagent/risk/`, `docs/technical_document.md` |

## Simulated, and why

| Part | What stands in | Why it cannot be real here | What a real company would do |
| --- | --- | --- | --- |
| The company and its records | Harbour Precision Components Ltd (fictional): 116 suppliers, orders, receipts, invoices | No company's books are available to a hackathon | Connect its ERP (Odoo, or CSV/Excel export) and mailbox |
| Settlement token | `MockUSDC`, at face value (1 token = $1), standing in for a bank's tokenised deposit | No bank issues tokenised deposits to a hackathon (HKMA Project Ensemble is a pilot) | Use the bank's deposit token, or the bank rail below |
| Bank | Bank-rail payments end in a pain.001 file; the demo bank on local chains turns a file into a camt.053 statement | No bank connection | Upload the file to its bank portal and import the bank's statement |
| Bank (as underwriter) and arbiter | Test keys we hold | No partner bank or arbitration body | The bank and an independent arbiter sign from their own wallets |
| Supplier email addresses | Sample addresses; supplier mail goes to a sandbox inbox (`fin-suppliers@agentmail.to`) with the intended recipient on top | The sample domains may belong to real companies | `MAIL_LIVE=on` sends to the registered addresses |
| Fapiao verification | A registry file of sample fapiao | No free official verification service | Set `FAPIAO_API_URL` to a verification provider |
| Error and loss rates for calibration | A stated simulator (`sim.py`) | No history of real bills | Calibrate on the company's own paid bills |
| Hosted demo chain | A local chain inside the container, fresh contracts per company | Judges' companies must not share caps, a pause switch or public test keys | Run on its own chain (FISCO BCOS) anchored to a public chain |
| Time | Demo windows in seconds (cool-down, dispute, coverage); the sample company keeps its demo date | A demo cannot wait days | Real windows; companies on a real ERP run on the calendar |

## Removed

The "naive agent" side-by-side demo and the "try your own attack" screen were removed from the product. The no-rules
agent survives only as a baseline column in the RED experiment (`results/red.json`).
