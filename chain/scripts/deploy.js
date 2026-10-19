// Deploys tUSDC, PaymentVault, BondPool, EvidenceAnchor and the naive demo wallet, funds them,
// registers the demo payees and sets the first bundle. Writes deployments/<network>.json.
//
//   npx hardhat run scripts/deploy.js --network baseSepolia
//   npx hardhat run scripts/deploy.js            (in-process local chain)
const fs = require("fs");
const path = require("path");
const { ethers, network } = require("hardhat");

const U = (x) => ethers.parseUnits(String(x), 6);
const id = (s) => ethers.encodeBytes32String(s);
const usd = (x) => U((Math.round(x * 100) / 100 / 1000).toFixed(6)); // 1 tUSDC stands for $1,000

// Written by `python -m apagent.demo` from the calibration (bundle r = K/N) and the demo ledger (payees).
const PARAMS_FILE = path.join(__dirname, "..", "..", "data", "demo", "deploy_params.json");
const P = fs.existsSync(PARAMS_FILE) ? JSON.parse(fs.readFileSync(PARAMS_FILE, "utf8")) : null;

// FISCO BCOS and Base Sepolia: time cannot be moved forward, so the demo uses a short "day" for the daily caps
// (DEMO_DAY_SECONDS) and the scripted tasks finish in one sitting. FISCO block timestamps are in milliseconds.
// Hardhat: seconds and 24-hour days (time is moved forward instead).
const IS_FISCO = network.name === "fisco";
const REAL_TIME = IS_FISCO || network.name === "baseSepolia";
const TIME_UNIT = IS_FISCO ? 1000 : 1;
const DAY_SECONDS = REAL_TIME ? Number(process.env.DEMO_DAY_SECONDS || 180) : 86400;

const DEMO = {
  pCap: usd(P ? P.pCapUsd : 5000), // P-CAP
  coolDown: REAL_TIME ? 60 : 300, // P-COOL (shorter where time cannot be moved forward)
  window: 300, // P-WINDOW
  disputeTime: 120, // P-DISPUTE
  vaultFunds: usd(P ? P.vaultUsd : 500000),
  naiveFunds: usd(P ? P.naiveUsd : 50000),
  poolFunds: usd(P ? P.poolUsd : 70000),
  bundle: P
    ? { mode: P.bundle.mode, pDay: usd(P.bundle.pDayUsd), pNDay: P.bundle.pNDay, pSupWeek: usd(P.bundle.pSupWeekUsd), r: usd(P.bundle.rUsd) }
    : { mode: 2, pDay: U(15), pNDay: 5, pSupWeek: U(5), r: U(0.4) },
};

async function main() {
  const signers = await ethers.getSigners();
  if (signers.length < 5) throw new Error("Need 5 keys: OWNER, AGENT, GOVERNOR, APPROVER, UNDERWRITER");
  const [owner, agent, governor, approver, underwriter] = signers;
  // The arbiter settles disputed reserve claims, so it must not be the company (owner) or the bank (underwriter).
  const local = ["localhost", "hardhat", "fisco"].includes(network.name);
  const arbiter = process.env.ARBITER_ADDRESS || (local ? signers[6]?.address : signers[5]?.address);
  if (!arbiter || [owner.address, underwriter.address, agent.address].includes(arbiter)) {
    throw new Error("The arbiter needs its own key: set ARBITER_ADDRESS, or ARBITER_KEY in chain/.env");
  }
  const attacker = process.env.ATTACKER_ADDRESS || (P && P.attacker) || ethers.Wallet.createRandom().address;

  const log = (k, v) => console.log(`${k.padEnd(14)} ${v}`);
  const wait = async (tx) => (await tx).wait();
  const out = { network: network.name, chainId: Number((await ethers.provider.getNetwork()).chainId), txs: {} };
  const record = async (name, txp) => {
    const rc = await wait(txp);
    out.txs[name] = rc.hash;
    return rc;
  };

  const token = await (await ethers.getContractFactory("MockUSDC", owner)).deploy();
  await token.waitForDeployment();
  const vault = await (await ethers.getContractFactory("PaymentVault", owner)).deploy(
    token, owner, agent, governor, approver, underwriter, DEMO.pCap, DEMO.coolDown, TIME_UNIT, DAY_SECONDS
  );
  await vault.waitForDeployment();
  const pool = await (await ethers.getContractFactory("BondPool", owner)).deploy(
    token, vault, arbiter, DEMO.window, DEMO.disputeTime, TIME_UNIT
  );
  await pool.waitForDeployment();
  const anchor = await (await ethers.getContractFactory("EvidenceAnchor", owner)).deploy(agent);
  await anchor.waitForDeployment();
  const naive = await (await ethers.getContractFactory("NaiveWallet", owner)).deploy(token, agent);
  await naive.waitForDeployment();

  await record("setPool", vault.connect(owner).setPool(pool));
  await record("mintVault", token.mint(vault, DEMO.vaultFunds));
  await record("mintNaive", token.mint(naive, DEMO.naiveFunds));
  await record("mintUnderwriter", token.mint(underwriter, DEMO.poolFunds));
  await record("approvePool", token.connect(underwriter).approve(pool, ethers.MaxUint256));
  await record("fundPool", pool.connect(underwriter).fund(DEMO.poolFunds));

  // Demo suppliers from the demo ledger; mainland payees use the bank rail.
  const payees = {};
  const list = P
    ? Object.entries(P.payees).map(([name, p]) => [name, p.wallet, p.rail])
    : [["ACME", ethers.Wallet.createRandom().address, 0], ["GANJIANG", ethers.ZeroAddress, 1]];
  for (const [name, wallet, rail] of list) {
    payees[name] = { wallet: ethers.getAddress(wallet), rail };
    await record(`addPayee_${name}`, vault.connect(owner).addPayee(id(name), ethers.getAddress(wallet), rail));
  }

  const b = DEMO.bundle;
  await record("proposeSettings", vault.connect(owner).proposeSettings(b.mode, b.pDay, b.pNDay, b.pSupWeek, b.r));
  const sid = (await vault.bundleCount()) - 1n;
  if (b.mode === 2) await record("approveSettings", vault.connect(underwriter).approveSettings(sid));
  // Approved payments above this amount need the owner's signature too (spec D4). DUAL_ABOVE_USD=0 turns it off.
  const dualAbove = usd(Number(process.env.DUAL_ABOVE_USD ?? 25000));
  await record("setDualAbove", vault.connect(owner).setDualAbove(dualAbove));

  Object.assign(out, {
    contracts: {
      token: await token.getAddress(),
      vault: await vault.getAddress(),
      pool: await pool.getAddress(),
      anchor: await anchor.getAddress(),
      naive: await naive.getAddress(),
    },
    roles: {
      owner: owner.address, agent: agent.address, governor: governor.address,
      approver: approver.address, underwriter: underwriter.address, arbiter, attacker,
    },
    payees,
    params: {
      pCap: DEMO.pCap.toString(), coolDown: DEMO.coolDown, window: DEMO.window,
      disputeTime: DEMO.disputeTime, activeSettings: Number(sid), timeUnit: TIME_UNIT, dayLength: DAY_SECONDS,
      dualAbove: dualAbove.toString(),
    },
    deployedAt: new Date().toISOString(),
  });

  // DEPLOY_OUT: write the record elsewhere (one deployment per company); default deployments/<network>.json.
  const target = process.env.DEPLOY_OUT || path.join(__dirname, "..", "deployments", `${network.name}.json`);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, JSON.stringify(out, null, 2));
  for (const [k, v] of Object.entries(out.contracts)) log(k, v);
  log("settings", `${sid} (mode ${b.mode})`);
  console.log(`\nPayees become active after the ${DEMO.coolDown}s cool-down.`);
}

main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
