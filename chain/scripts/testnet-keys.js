// Base Sepolia role keys: create, show, fund.
//
//   node scripts/testnet-keys.js           create any missing role keys in chain/.env, print addresses and balances
//   node scripts/testnet-keys.js --fund    also send ETH from the owner to every role below FUND_ETH (default 0.003)
//
// Fund the owner address from a faucet first; --fund then shares it out. Test keys only: never mainnet keys.
const fs = require("fs");
const path = require("path");
const { ethers } = require("ethers");

const ENV = path.join(__dirname, "..", ".env");
// ATTACKER is an unrelated key for the red-team task that calls the vault from outside (task 9).
const ROLES = ["OWNER", "AGENT", "GOVERNOR", "APPROVER", "UNDERWRITER", "ATTACKER"];
const FUND_ETH = process.env.FUND_ETH || "0.003";

function readEnv() {
  const src = fs.existsSync(ENV) ? ENV : path.join(__dirname, "..", ".env.example");
  return fs.readFileSync(src, "utf8");
}

function ensureKeys(text) {
  let created = 0;
  for (const r of ROLES) {
    const re = new RegExp(`^${r}_KEY=(.*)$`, "m");
    const m = text.match(re);
    if (m && m[1].trim()) continue;
    const key = ethers.Wallet.createRandom().privateKey;
    text = m ? text.replace(re, `${r}_KEY=${key}`) : `${text.trimEnd()}\n${r}_KEY=${key}\n`;
    created++;
  }
  if (created || !fs.existsSync(ENV)) fs.writeFileSync(ENV, text);
  return created;
}

async function main() {
  const created = ensureKeys(readEnv());
  if (created) console.log(`Created ${created} key(s) in chain/.env (git ignores it).`);
  require("dotenv").config({ path: ENV, override: true });

  const provider = new ethers.JsonRpcProvider(process.env.BASE_SEPOLIA_RPC || "https://sepolia.base.org");
  const wallets = Object.fromEntries(ROLES.map((r) => [r, new ethers.Wallet(process.env[`${r}_KEY`], provider)]));
  const target = ethers.parseEther(FUND_ETH);

  if (process.argv.includes("--fund")) {
    const owner = wallets.OWNER;
    let nonce = await provider.getTransactionCount(owner.address, "pending");
    for (const r of ROLES.slice(1)) {
      const bal = await provider.getBalance(wallets[r].address);
      if (bal >= target) continue;
      const tx = await owner.sendTransaction({ to: wallets[r].address, value: target - bal, nonce: nonce++ });
      console.log(`funding ${r.toLowerCase()}: ${tx.hash}`);
      await tx.wait();
    }
  }

  console.log("\nrole         address                                     ETH");
  for (const r of ROLES) {
    const bal = await provider.getBalance(wallets[r].address);
    console.log(`${r.toLowerCase().padEnd(12)} ${wallets[r].address}  ${ethers.formatEther(bal)}`);
  }
  console.log(`\nFaucet the owner address, then run with --fund. Each role needs about ${FUND_ETH} ETH.`);
}

main().catch((e) => {
  console.error(e.message || e);
  process.exit(1);
});
