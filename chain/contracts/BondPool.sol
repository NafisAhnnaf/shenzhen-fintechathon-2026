// SPDX-License-Identifier: MIT
pragma solidity ^0.8.11;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {EIP712} from "@openzeppelin/contracts/utils/cryptography/EIP712.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import {IBondPool} from "./IBondPool.sol";

interface IVaultView {
    function owner() external view returns (address);
    function approver() external view returns (address);
    function underwriter() external view returns (address);
    function pCap() external view returns (uint256);
}

/// @title BondPool
/// @notice Performance reserve for autonomous (T1) payments (plan section 7.3). Not an insurance policy.
/// Each open T1 payment locks r. Claims pay only the company treasury (the vault), at most the amount paid.
contract BondPool is IBondPool, EIP712 {
    using SafeERC20 for IERC20;

    enum Status { None, Locked, Released, Filed, Disputed, Resolved, Paid }
    enum Cause { None, Overpayment, Duplicate, WrongPayee }

    struct Lock {
        uint256 amount; // amount paid to the supplier
        uint256 r; // reserve locked for this payment
        uint64 lockedAt;
        uint8 mode; // 1 self-reserve, 2 bonded
        Status status;
        uint256 loss; // claimed (then approved) loss
        uint64 disputeUntil;
        uint256 claimPaid;
        uint256 recovered;
        Cause cause;
        bytes32 evidence;
    }

    bytes32 private constant CLAIM_TYPEHASH =
        keccak256("Claim(bytes32 billId,uint256 loss,uint8 cause,bytes32 evidence,uint256 expiry)");

    IERC20 public immutable token;
    address public immutable vault;
    address public immutable arbiter;
    uint64 public immutable window; // P-WINDOW
    uint64 public immutable disputeTime; // P-DISPUTE
    uint256 public immutable timeUnit; // 1 on EVM chains, 1000 on FISCO BCOS (millisecond timestamps)

    uint256 public lockedTotal;
    uint256 public owedTotal; // shortfall recorded when free capital is not enough
    bool public paused;

    mapping(bytes32 => Lock) public locks;
    mapping(address => uint256) public deposited;

    event Funded(address indexed funder, uint256 amount);
    event Withdrawn(address indexed funder, uint256 amount);
    event Locked(bytes32 indexed billId, uint256 amount, uint256 r);
    event Released(bytes32 indexed billId, uint256 r);
    event ClaimFiled(bytes32 indexed billId, uint256 loss, Cause cause, bytes32 evidence);
    event ClaimDisputed(bytes32 indexed billId);
    event ClaimResolved(bytes32 indexed billId, uint256 approvedLoss);
    event ClaimPaid(bytes32 indexed billId, uint256 paid, uint256 owed);
    event RecoveryRecorded(bytes32 indexed billId, uint256 amount);
    event PoolPaused(address by);
    event PoolUnpaused(address by);

    error NotAuthorized();
    error PoolIsPaused();
    error InsufficientCapital();
    error BadState();
    error OutsideWindow();
    error BadClaim();
    error BadSignature();
    error Expired();

    modifier onlyVault() {
        if (msg.sender != vault) revert NotAuthorized();
        _;
    }

    modifier onlyFunder() {
        if (msg.sender != IVaultView(vault).owner() && msg.sender != IVaultView(vault).underwriter()) {
            revert NotAuthorized();
        }
        _;
    }

    constructor(IERC20 token_, address vault_, address arbiter_, uint64 window_, uint64 disputeTime_, uint256 timeUnit_)
        EIP712("BondPool", "1")
    {
        require(timeUnit_ == 1 || timeUnit_ == 1000, "time unit");
        require(address(token_) != address(0) && vault_ != address(0) && arbiter_ != address(0), "zero address");
        timeUnit = timeUnit_;
        token = token_;
        vault = vault_;
        arbiter = arbiter_;
        window = window_;
        disputeTime = disputeTime_;
    }

    /// @notice Current time in seconds on any chain.
    function nowSeconds() public view returns (uint256) {
        return block.timestamp / timeUnit;
    }

    // ---------------------------------------------------------------- capital

    function balance() public view returns (uint256) {
        return token.balanceOf(address(this));
    }

    function freeCapital() public view returns (uint256) {
        uint256 b = balance();
        return b > lockedTotal ? b - lockedTotal : 0;
    }

    function fund(uint256 amount) external onlyFunder {
        token.safeTransferFrom(msg.sender, address(this), amount);
        deposited[msg.sender] += amount;
        emit Funded(msg.sender, amount);
    }

    function withdraw(uint256 amount) external onlyFunder {
        if (amount > deposited[msg.sender] || balance() < lockedTotal + amount) revert InsufficientCapital();
        deposited[msg.sender] -= amount;
        token.safeTransfer(msg.sender, amount);
        emit Withdrawn(msg.sender, amount);
        _autoPause();
    }

    function pause() external onlyFunder {
        paused = true;
        emit PoolPaused(msg.sender);
    }

    function unpause() external onlyFunder {
        if (freeCapital() < IVaultView(vault).pCap() || owedTotal > 0) revert InsufficientCapital();
        paused = false;
        emit PoolUnpaused(msg.sender);
    }

    // ---------------------------------------------------------------- locks

    /// @notice Called by the vault before every T1 payment in a reserve mode.
    /// Free capital after the lock must still cover a total loss of this payment (B3).
    function lock(bytes32 billId, uint256 amount, uint256 r, uint8 mode) external onlyVault {
        if (paused) revert PoolIsPaused();
        if (locks[billId].status != Status.None) revert BadState();
        if (lockedTotal + r + amount > balance()) revert InsufficientCapital();
        lockedTotal += r;
        locks[billId] = Lock({
            amount: amount,
            r: r,
            lockedAt: uint64(nowSeconds()),
            mode: mode,
            status: Status.Locked,
            loss: 0,
            disputeUntil: 0,
            claimPaid: 0,
            recovered: 0,
            cause: Cause.None,
            evidence: bytes32(0)
        });
        emit Locked(billId, amount, r);
        _autoPause();
    }

    /// @notice Anyone can release a lock after the window if no claim is open.
    function release(bytes32 billId) external {
        Lock storage l = locks[billId];
        if (l.status != Status.Locked) revert BadState();
        if (nowSeconds() <= l.lockedAt + window) revert OutsideWindow();
        l.status = Status.Released;
        lockedTotal -= l.r;
        emit Released(billId, l.r);
    }

    // ---------------------------------------------------------------- claims

    /// @notice Files a claim inside the window. Needs the finance manager's EIP-712 signature,
    /// so the agent key alone cannot file one (B13).
    function fileClaim(bytes32 billId, uint256 loss, Cause cause, bytes32 evidence, uint256 expiry, bytes calldata sig)
        external
    {
        if (nowSeconds() > expiry) revert Expired();
        Lock storage l = locks[billId];
        if (l.status != Status.Locked) revert BadState();
        if (nowSeconds() > l.lockedAt + window) revert OutsideWindow();
        if (loss == 0 || loss > l.amount || cause == Cause.None) revert BadClaim();
        bytes32 digest =
            _hashTypedDataV4(keccak256(abi.encode(CLAIM_TYPEHASH, billId, loss, uint8(cause), evidence, expiry)));
        if (ECDSA.recover(digest, sig) != IVaultView(vault).approver()) revert BadSignature();
        l.status = Status.Filed;
        l.loss = loss;
        l.cause = cause;
        l.evidence = evidence;
        l.disputeUntil = l.mode == 2 ? uint64(nowSeconds()) + disputeTime : uint64(nowSeconds());
        emit ClaimFiled(billId, loss, cause, evidence);
    }

    /// @notice Bonded mode only: the underwriter disputes inside the dispute time.
    function dispute(bytes32 billId) external {
        Lock storage l = locks[billId];
        if (msg.sender != IVaultView(vault).underwriter()) revert NotAuthorized();
        if (l.status != Status.Filed || l.mode != 2 || nowSeconds() > l.disputeUntil) revert BadState();
        l.status = Status.Disputed;
        emit ClaimDisputed(billId);
    }

    function resolve(bytes32 billId, uint256 approvedLoss) external {
        if (msg.sender != arbiter) revert NotAuthorized();
        Lock storage l = locks[billId];
        if (l.status != Status.Disputed || approvedLoss > l.loss) revert BadState();
        l.loss = approvedLoss;
        l.status = Status.Resolved;
        emit ClaimResolved(billId, approvedLoss);
    }

    /// @notice Pays min(loss, r + free capital) to the company treasury. Once per bill (B4).
    function executeClaim(bytes32 billId) external {
        Lock storage l = locks[billId];
        if (l.status == Status.Filed) {
            // Bonded: wait out the underwriter's dispute time. Self-reserve: immediate.
            if (l.mode == 2 && nowSeconds() <= l.disputeUntil) revert BadState();
        } else if (l.status != Status.Resolved) {
            revert BadState();
        }
        l.status = Status.Paid;
        uint256 available = l.r + freeCapital(); // before unlocking, so r is not counted twice
        lockedTotal -= l.r;
        uint256 pay = l.loss < available ? l.loss : available;
        uint256 owed = l.loss - pay;
        l.claimPaid = pay;
        if (owed > 0) {
            owedTotal += owed;
            paused = true;
            emit PoolPaused(address(this));
        }
        if (pay > 0) token.safeTransfer(vault, pay);
        emit ClaimPaid(billId, pay, owed);
        _autoPause();
    }

    // ---------------------------------------------------------------- recoveries

    function recoverable(bytes32 billId) external view returns (uint256) {
        Lock storage l = locks[billId];
        return l.claimPaid - l.recovered;
    }

    /// @notice The vault has already transferred the recovered amount here (B5: never above the claim paid).
    function recordRecovery(bytes32 billId, uint256 amount) external onlyVault {
        Lock storage l = locks[billId];
        if (amount > l.claimPaid - l.recovered) revert BadClaim();
        l.recovered += amount;
        emit RecoveryRecorded(billId, amount);
    }

    function domainSeparator() external view returns (bytes32) {
        return _domainSeparatorV4();
    }

    function _autoPause() internal {
        if (!paused && freeCapital() < IVaultView(vault).pCap()) {
            paused = true;
            emit PoolPaused(address(this));
        }
    }
}
