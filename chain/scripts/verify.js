// Publishes the source of every deployed contract on the network's explorer (sepolia.basescan.org for Base Sepolia),
// with the constructor arguments read back from deployments/<network>.json. Safe to run again.
//
//   npx hardhat run scripts/verify.js --network baseSepolia
const fs = require("fs");
const path = require("path");
const { network, run } = require("hardhat");

async function main() {
  const dep = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "deployments", `${network.name}.json`), "utf8"));
  const c = dep.contracts, r = dep.roles, p = dep.params;
  const jobs = [
    ["token", "contracts/MockUSDC.sol:MockUSDC", []],
    ["vault", "contracts/PaymentVault.sol:PaymentVault",
      [c.token, r.owner, r.agent, r.governor, r.approver, r.underwriter, p.pCap, p.coolDown, p.timeUnit, p.dayLength]],
    ["pool", "contracts/BondPool.sol:BondPool", [c.token, c.vault, r.arbiter, p.window, p.disputeTime, p.timeUnit]],
    ["anchor", "contracts/EvidenceAnchor.sol:EvidenceAnchor", [r.agent]],
  ];
  for (const [name, contract, args] of jobs) {
    if (!c[name]) continue;
    try {
      await run("verify:verify", { address: c[name], contract, constructorArguments: args });
      console.log(`${name.padEnd(8)} verified  ${c[name]}`);
    } catch (e) {
      const msg = String(e.message || e);
      if (/already verified/i.test(msg)) console.log(`${name.padEnd(8)} already verified  ${c[name]}`);
      else console.log(`${name.padEnd(8)} FAILED  ${msg.split("\n")[0]}`);
    }
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
