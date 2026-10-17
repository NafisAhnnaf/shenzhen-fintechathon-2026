require("@nomicfoundation/hardhat-ethers");
require("@nomicfoundation/hardhat-chai-matchers");
require("dotenv").config();
const path = require("path");
const { subtask } = require("hardhat/config");
const {
  TASK_COMPILE_SOLIDITY_GET_SOURCE_PATHS,
  TASK_TEST_GET_TEST_FILES,
} = require("hardhat/builtin-tasks/task-names");

// macOS writes "._*" metadata files on non-APFS drives. Keep them out of compile and test.
const notAppleDouble = (p) => !path.basename(p).startsWith("._");
subtask(TASK_COMPILE_SOLIDITY_GET_SOURCE_PATHS).setAction(async (_, __, runSuper) =>
  (await runSuper()).filter(notAppleDouble)
);
subtask(TASK_TEST_GET_TEST_FILES).setAction(async (args, __, runSuper) =>
  (await runSuper(args)).filter(notAppleDouble)
);

const keys = [
  process.env.OWNER_KEY,
  process.env.AGENT_KEY,
  process.env.GOVERNOR_KEY,
  process.env.APPROVER_KEY,
  process.env.UNDERWRITER_KEY,
].filter(Boolean);

module.exports = {
  solidity: {
    // 0.8.11 and london: the newest FISCO BCOS v3 accepts. The same bytecode runs on Hardhat and Base Sepolia.
    version: "0.8.11",
    settings: { optimizer: { enabled: true, runs: 200 }, evmVersion: "london" },
  },
  networks: {
    localhost: { url: "http://127.0.0.1:8545", gas: "auto" },
    // Local four-node FISCO BCOS v3 chain (Air), web3 RPC on node0. No gas fees: legacy transactions at price 0.
    // Uses the same public test mnemonic as Hardhat (local consortium chain only).
    fisco: {
      url: process.env.FISCO_RPC || "http://127.0.0.1:8546",
      chainId: 20200,
      gasPrice: 0,
      accounts: { mnemonic: "test test test test test test test test test test test junk", count: 6 },
    },
    baseSepolia: {
      url: process.env.BASE_SEPOLIA_RPC || "https://sepolia.base.org",
      chainId: 84532,
      accounts: keys,
    },
  },
};
