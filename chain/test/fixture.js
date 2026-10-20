const { ethers } = require("hardhat");
const { time } = require("@nomicfoundation/hardhat-network-helpers");

const U = (x) => ethers.parseUnits(String(x), 6); // tUSDC base units (the tests count in tokens)
const id = (s) => ethers.encodeBytes32String(s);

const Mode = { Standard: 0, SelfReserve: 1, Bonded: 2 };
const Rail = { Token: 0, Bank: 1 };
const Cause = { None: 0, Overpayment: 1, Duplicate: 2, WrongPayee: 3 };

const P_CAP = U(5);
const COOL = 300; // P-COOL, 5 min in the demo
const WINDOW = 300; // P-WINDOW
const DISPUTE = 120; // P-DISPUTE

async function deploy() {
  const [owner, agent, governor, approver, underwriter, arbiter, acme, jiangxi, attacker] =
    await ethers.getSigners();

  const token = await (await ethers.getContractFactory("MockUSDC")).deploy();
  const vault = await (await ethers.getContractFactory("PaymentVault")).deploy(
    token, owner, agent, governor, approver, underwriter, P_CAP, COOL, 1, 86400
  );
  const pool = await (await ethers.getContractFactory("BondPool")).deploy(
    token, vault, arbiter, WINDOW, DISPUTE, 1
  );
  await vault.connect(owner).setPool(pool);

  await token.mint(vault, U(1000));
  await token.mint(owner, U(200));
  await token.mint(underwriter, U(200));
  await token.connect(underwriter).approve(pool, ethers.MaxUint256);
  await token.connect(owner).approve(pool, ethers.MaxUint256);

  await vault.connect(owner).addPayee(id("ACME"), acme, Rail.Token);
  await vault.connect(owner).addPayee(id("JIANGXI"), ethers.ZeroAddress, Rail.Bank);
  await time.increase(COOL + 1);

  const chainId = (await ethers.provider.getNetwork()).chainId;
  const vaultDomain = { name: "PaymentVault", version: "1", chainId, verifyingContract: await vault.getAddress() };
  const poolDomain = { name: "BondPool", version: "1", chainId, verifyingContract: await pool.getAddress() };

  const govTypes = {
    GovApproval: [
      { name: "billId", type: "bytes32" },
      { name: "supplierId", type: "bytes32" },
      { name: "amount", type: "uint256" },
      { name: "settingsId", type: "uint256" },
      { name: "expiry", type: "uint256" },
      { name: "inputHash", type: "bytes32" },
    ],
  };
  const payTypes = {
    PaymentApproval: [
      { name: "billId", type: "bytes32" },
      { name: "payee", type: "address" },
      { name: "amount", type: "uint256" },
      { name: "expiry", type: "uint256" },
    ],
  };
  const recvTypes = {
    ReceivableApproval: [
      { name: "billId", type: "bytes32" },
      { name: "amount", type: "uint256" },
      { name: "expiry", type: "uint256" },
    ],
  };
  const claimTypes = {
    Claim: [
      { name: "billId", type: "bytes32" },
      { name: "loss", type: "uint256" },
      { name: "cause", type: "uint8" },
      { name: "evidence", type: "bytes32" },
      { name: "expiry", type: "uint256" },
    ],
  };

  const expiry = async () => (await time.latest()) + 3600;
  const inputHash = ethers.keccak256(ethers.toUtf8Bytes("bill-input"));

  const s = {
    owner, agent, governor, approver, underwriter, arbiter, acme, jiangxi, attacker,
    token, vault, pool, inputHash, expiry,

    async govSig(billId, supplierId, amount, settingsId, exp, signer = governor) {
      return signer.signTypedData(vaultDomain, govTypes, {
        billId, supplierId, amount, settingsId, expiry: exp, inputHash,
      });
    },

    /** T1 payment as the agent, with a valid governor signature. */
    async payT1(bill, supplier, amount, opts = {}) {
      const exp = opts.expiry ?? (await expiry());
      const settingsId = opts.settingsId ?? (await vault.activeSettings());
      const sig = await s.govSig(id(bill), id(supplier), amount, settingsId, exp, opts.signer);
      return vault.connect(opts.caller ?? agent)
        .payAutonomous(id(bill), id(supplier), amount, settingsId, exp, inputHash, sig);
    },

    async payT2(bill, supplier, amount, opts = {}) {
      const exp = opts.expiry ?? (await expiry());
      const payee = (await vault.payees(id(supplier))).wallet;
      const sig = await (opts.signer ?? approver).signTypedData(vaultDomain, payTypes, {
        billId: id(bill), payee, amount, expiry: exp,
      });
      return vault.connect(opts.caller ?? agent).payApproved(id(bill), id(supplier), amount, exp, sig);
    },

    /** T2 above dualAbove: the finance manager and the owner both sign the same PaymentApproval. */
    async payT2Dual(bill, supplier, amount, opts = {}) {
      const exp = opts.expiry ?? (await expiry());
      const payee = (await vault.payees(id(supplier))).wallet;
      const msg = { billId: id(bill), payee, amount, expiry: exp };
      const sig = await (opts.signer ?? approver).signTypedData(vaultDomain, payTypes, msg);
      const ownerSig = await (opts.second ?? owner).signTypedData(vaultDomain, payTypes, msg);
      return vault.connect(agent).payApprovedDual(id(bill), id(supplier), amount, exp, sig, ownerSig);
    },

    async openReceivable(bill, amount, signer = approver) {
      const exp = await expiry();
      const sig = await signer.signTypedData(vaultDomain, recvTypes, { billId: id(bill), amount, expiry: exp });
      return vault.connect(agent).openReceivable(id(bill), amount, exp, sig);
    },

    async fileClaim(bill, loss, cause = Cause.Overpayment, signer = approver) {
      const exp = await expiry();
      const evidence = ethers.keccak256(ethers.toUtf8Bytes(`evidence:${bill}`));
      const sig = await signer.signTypedData(poolDomain, claimTypes, {
        billId: id(bill), loss, cause, evidence, expiry: exp,
      });
      return pool.connect(agent).fileClaim(id(bill), loss, cause, evidence, exp, sig);
    },

    /** Owner sets a standard or self-reserve bundle; a bonded one also needs the underwriter. */
    async setBundle(mode, { pDay = U(15), pNDay = 5, pSupWeek = U(5), r = U(0.25) } = {}) {
      await vault.connect(owner).proposeSettings(mode, pDay, pNDay, pSupWeek, r);
      const sid = (await vault.bundleCount()) - 1n;
      if (mode === Mode.Bonded) await vault.connect(underwriter).approveSettings(sid);
      return sid;
    },
  };
  return s;
}

module.exports = { deploy, U, id, Mode, Rail, Cause, P_CAP, COOL, WINDOW, DISPUTE };
