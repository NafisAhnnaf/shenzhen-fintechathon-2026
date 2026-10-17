// SPDX-License-Identifier: MIT
pragma solidity ^0.8.11;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {EIP712} from "@openzeppelin/contracts/utils/cryptography/EIP712.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import {IBondPool} from "./IBondPool.sol";

/// @title PaymentVault
/// @notice Holds the company's payables funds and enforces every payment rule (plan section 7.2).
/// The agent key can pay inside the rules, freeze a payee and pause itself. It has no admin rights.
contract PaymentVault is EIP712 {
    using SafeERC20 for IERC20;

    enum Rail { Token, Bank }
    enum Mode { Standard, SelfReserve, Bonded }

    struct Payee {
        address wallet;
        Rail rail;
        uint64 activeAt;
        bool exists;
        bool frozen;
    }

    /// @dev One risk-dial position. P-CAP is fixed for the vault, so it is not part of a bundle.
    struct Bundle {
        Mode mode;
        uint128 pDay; // daily T1 amount cap
        uint32 pNDay; // daily T1 count cap
        uint128 pSupWeek; // T1 total per supplier per 7-day bucket
        uint128 r; // reserve locked per T1 payment (reserve modes)
        bool underwriterOk;
        bool exists;
    }

    struct Paid {
        bytes32 supplierId;
        uint256 amount;
        bool autonomous;
    }

    struct Receivable {
        bytes32 supplierId;
        uint256 open;
        bool opened;
    }

    bytes32 private constant GOV_TYPEHASH = keccak256(
        "GovApproval(bytes32 billId,bytes32 supplierId,uint256 amount,uint256 settingsId,uint256 expiry,bytes32 inputHash)"
    );
    bytes32 private constant PAY_TYPEHASH =
        keccak256("PaymentApproval(bytes32 billId,address payee,uint256 amount,uint256 expiry)");
    bytes32 private constant RECV_TYPEHASH =
        keccak256("ReceivableApproval(bytes32 billId,uint256 amount,uint256 expiry)");

    IERC20 public immutable token;
    address public immutable owner;
    uint256 public immutable pCap;
    uint64 public immutable coolDown;
    /// @notice 1 on EVM chains (seconds); 1000 on FISCO BCOS, whose block timestamps are in milliseconds.
    uint256 public immutable timeUnit;
    /// @notice Length of a "day" for the daily and weekly caps, in seconds (86400; shorter in a compressed demo).
    uint256 public immutable dayLength;

    address public agent;
    address public governor;
    address public approver;
    address public underwriter;
    IBondPool public pool;

    bool public agentPaused;
    uint256 public activeSettings;
    bool public hasActiveSettings;
    Bundle[] private _bundles;

    mapping(bytes32 => Payee) public payees;
    mapping(bytes32 => bool) public billUsed;
    mapping(bytes32 => Paid) public paid;
    mapping(bytes32 => Receivable) public receivables;
    mapping(uint256 => uint256) public dayAmount;
    mapping(uint256 => uint256) public dayCount;
    mapping(bytes32 => mapping(uint256 => uint256)) public supplierWeekAmount;

    event PayeeAdded(bytes32 indexed id, address wallet, Rail rail, uint64 activeAt);
    event PayeeFrozen(bytes32 indexed id, address by);
    event PayeeUnfrozen(bytes32 indexed id);
    event SettingsProposed(uint256 indexed id, Mode mode, uint128 pDay, uint32 pNDay, uint128 pSupWeek, uint128 r);
    event SettingsApproved(uint256 indexed id, address by);
    event SettingsActivated(uint256 indexed id);
    event PaidAutonomous(bytes32 indexed billId, bytes32 indexed supplierId, uint256 amount, uint256 settingsId, bytes32 inputHash);
    event PaidApproved(bytes32 indexed billId, bytes32 indexed supplierId, uint256 amount);
    event BankPaymentRecorded(bytes32 indexed billId, bytes32 indexed supplierId, uint256 amount, bytes32 bankRef);
    event ReceivableOpened(bytes32 indexed billId, bytes32 indexed supplierId, uint256 amount);
    event OffsetRecorded(bytes32 indexed billId, bytes32 indexed againstBillId, uint256 amount, uint256 toPool);
    event AgentPaused(address by);
    event AgentUnpaused();
    event RoleSet(string role, address account);

    error NotAuthorized();
    error AgentIsPaused();
    error Expired();
    error BadSignature();
    error BillAlreadyPaid();
    error PayeeNotActive();
    error PayeeIsFrozen();
    error OverPaymentCap();
    error OverDailyAmount();
    error OverDailyCount();
    error OverSupplierWeek();
    error WrongSettings();
    error NoSuchSettings();
    error NeedsUnderwriter();
    error BadReceivable();
    error PoolNotSet();

    modifier only(address who) {
        if (msg.sender != who) revert NotAuthorized();
        _;
    }

    constructor(
        IERC20 token_,
        address owner_,
        address agent_,
        address governor_,
        address approver_,
        address underwriter_,
        uint256 pCap_,
        uint64 coolDown_,
        uint256 timeUnit_,
        uint256 dayLength_
    ) EIP712("PaymentVault", "1") {
        require(timeUnit_ == 1 || timeUnit_ == 1000, "time unit");
        require(dayLength_ > 0, "day length");
        require(agent_ != owner_ && agent_ != governor_ && agent_ != approver_, "agent key must be separate");
        token = token_;
        owner = owner_;
        agent = agent_;
        governor = governor_;
        approver = approver_;
        underwriter = underwriter_;
        pCap = pCap_;
        coolDown = coolDown_;
        timeUnit = timeUnit_;
        dayLength = dayLength_;
    }

    /// @notice Current time in seconds on any chain.
    function nowSeconds() public view returns (uint256) {
        return block.timestamp / timeUnit;
    }

    // ---------------------------------------------------------------- owner (T3)

    function setPool(IBondPool pool_) external only(owner) {
        require(address(pool) == address(0), "pool already set");
        pool = pool_;
    }

    function setAgent(address a) external only(owner) {
        require(a != owner && a != governor && a != approver, "agent key must be separate");
        agent = a;
        emit RoleSet("agent", a);
    }

    function setGovernor(address a) external only(owner) {
        require(a != agent, "agent key must be separate");
        governor = a;
        emit RoleSet("governor", a);
    }

    function setApprover(address a) external only(owner) {
        require(a != agent, "agent key must be separate");
        approver = a;
        emit RoleSet("approver", a);
    }

    /// @notice Adds or changes a payee. It cannot be paid until the cool-down ends.
    function addPayee(bytes32 id, address wallet, Rail rail) external only(owner) {
        require(rail == Rail.Bank || wallet != address(0), "wallet required");
        uint64 activeAt = uint64(nowSeconds()) + coolDown;
        Payee storage p = payees[id];
        p.wallet = wallet;
        p.rail = rail;
        p.activeAt = activeAt;
        p.exists = true;
        emit PayeeAdded(id, wallet, rail, activeAt);
    }

    function unfreezePayee(bytes32 id) external only(owner) {
        payees[id].frozen = false;
        emit PayeeUnfrozen(id);
    }

    function unpauseAgent() external only(owner) {
        agentPaused = false;
        emit AgentUnpaused();
    }

    /// @notice Proposes a settings bundle. Standard and self-reserve bundles activate at once;
    /// bonded bundles activate when the underwriter approves.
    function proposeSettings(Mode mode, uint128 pDay, uint32 pNDay, uint128 pSupWeek, uint128 r)
        external
        only(owner)
        returns (uint256 id)
    {
        if (mode != Mode.Standard && address(pool) == address(0)) revert PoolNotSet();
        if (mode == Mode.Standard) r = 0;
        id = _bundles.length;
        _bundles.push(Bundle(mode, pDay, pNDay, pSupWeek, r, false, true));
        emit SettingsProposed(id, mode, pDay, pNDay, pSupWeek, r);
        if (mode != Mode.Bonded) _activate(id);
    }

    function approveSettings(uint256 id) external only(underwriter) {
        Bundle storage b = _bundle(id);
        b.underwriterOk = true;
        emit SettingsApproved(id, msg.sender);
        _activate(id);
    }

    /// @notice Switches back to an earlier bundle that already has every approval it needs.
    function activateSettings(uint256 id) external only(owner) {
        _activate(id);
    }

    function withdraw(address to, uint256 amount) external only(owner) {
        token.safeTransfer(to, amount);
    }

    // ---------------------------------------------------------------- protective (P)

    function freezePayee(bytes32 id) external {
        if (msg.sender != owner && msg.sender != governor && msg.sender != agent) revert NotAuthorized();
        payees[id].frozen = true;
        emit PayeeFrozen(id, msg.sender);
    }

    function pauseAgent() external {
        if (msg.sender != owner && msg.sender != governor && msg.sender != agent) revert NotAuthorized();
        agentPaused = true;
        emit AgentPaused(msg.sender);
    }

    // ---------------------------------------------------------------- payments

    /// @notice T1: autonomous payment, co-signed by the governor, inside every cap.
    function payAutonomous(
        bytes32 billId,
        bytes32 supplierId,
        uint256 amount,
        uint256 settingsId,
        uint256 expiry,
        bytes32 inputHash,
        bytes calldata govSig
    ) external only(agent) {
        if (agentPaused) revert AgentIsPaused();
        if (nowSeconds() > expiry) revert Expired();
        if (!hasActiveSettings || settingsId != activeSettings) revert WrongSettings();
        bytes32 digest = _hashTypedDataV4(
            keccak256(abi.encode(GOV_TYPEHASH, billId, supplierId, amount, settingsId, expiry, inputHash))
        );
        if (ECDSA.recover(digest, govSig) != governor) revert BadSignature();
        Payee memory p = _checkPayee(billId, supplierId);

        Bundle memory b = _bundles[settingsId];
        _applyCaps(supplierId, amount, b);
        // The reserve comes from the stored bundle, never from the caller (B12).
        if (b.mode != Mode.Standard) pool.lock(billId, amount, b.r, uint8(b.mode));

        _send(billId, supplierId, p, amount, true);
        emit PaidAutonomous(billId, supplierId, amount, settingsId, inputHash);
    }

    /// @notice T2: payment approved by the finance manager's EIP-712 signature. Works while the agent is paused.
    function payApproved(bytes32 billId, bytes32 supplierId, uint256 amount, uint256 expiry, bytes calldata sig)
        external
        only(agent)
    {
        if (nowSeconds() > expiry) revert Expired();
        Payee memory p = _checkPayee(billId, supplierId);
        bytes32 digest =
            _hashTypedDataV4(keccak256(abi.encode(PAY_TYPEHASH, billId, p.wallet, amount, expiry)));
        if (ECDSA.recover(digest, sig) != approver) revert BadSignature();
        _send(billId, supplierId, p, amount, false);
        emit PaidApproved(billId, supplierId, amount);
    }

    // ---------------------------------------------------------------- recovery

    /// @notice Opens a receivable for a confirmed overpayment on a paid bill (manager signature).
    function openReceivable(bytes32 billId, uint256 amount, uint256 expiry, bytes calldata sig) external only(agent) {
        if (nowSeconds() > expiry) revert Expired();
        bytes32 digest = _hashTypedDataV4(keccak256(abi.encode(RECV_TYPEHASH, billId, amount, expiry)));
        if (ECDSA.recover(digest, sig) != approver) revert BadSignature();
        Paid memory pd = paid[billId];
        Receivable storage rc = receivables[billId];
        if (pd.amount == 0 || amount == 0 || amount > pd.amount || rc.opened) revert BadReceivable();
        rc.supplierId = pd.supplierId;
        rc.open = amount;
        rc.opened = true;
        emit ReceivableOpened(billId, pd.supplierId, amount);
    }

    /// @notice Records a recovery deducted from a later invoice of the same supplier.
    /// If the reserve already repaid this bill, the recovered amount goes back to the reserve.
    function recordOffset(bytes32 billId, bytes32 againstBillId, uint256 amount) external only(agent) {
        Receivable storage rc = receivables[billId];
        if (amount == 0 || amount > rc.open) revert BadReceivable();
        if (!billUsed[againstBillId] || paid[againstBillId].supplierId != rc.supplierId || againstBillId == billId) {
            revert BadReceivable();
        }
        rc.open -= amount;
        uint256 toPool;
        if (address(pool) != address(0)) {
            uint256 rec = pool.recoverable(billId);
            toPool = amount < rec ? amount : rec;
            if (toPool > 0) {
                token.safeTransfer(address(pool), toPool);
                pool.recordRecovery(billId, toPool);
            }
        }
        emit OffsetRecorded(billId, againstBillId, amount, toPool);
    }

    // ---------------------------------------------------------------- views

    function bundle(uint256 id) external view returns (Bundle memory) {
        return _bundle(id);
    }

    function bundleCount() external view returns (uint256) {
        return _bundles.length;
    }

    function activeMode() external view returns (Mode) {
        return _bundles[activeSettings].mode;
    }

    function domainSeparator() external view returns (bytes32) {
        return _domainSeparatorV4();
    }

    // ---------------------------------------------------------------- internal

    function _bundle(uint256 id) internal view returns (Bundle storage) {
        if (id >= _bundles.length) revert NoSuchSettings();
        return _bundles[id];
    }

    function _activate(uint256 id) internal {
        Bundle storage b = _bundle(id);
        if (b.mode == Mode.Bonded && !b.underwriterOk) revert NeedsUnderwriter();
        activeSettings = id;
        hasActiveSettings = true;
        emit SettingsActivated(id);
    }

    function _applyCaps(bytes32 supplierId, uint256 amount, Bundle memory b) internal {
        if (amount > pCap) revert OverPaymentCap();
        uint256 day = nowSeconds() / dayLength;
        uint256 week = nowSeconds() / (7 * dayLength);
        if (dayAmount[day] + amount > b.pDay) revert OverDailyAmount();
        if (dayCount[day] + 1 > b.pNDay) revert OverDailyCount();
        if (supplierWeekAmount[supplierId][week] + amount > b.pSupWeek) revert OverSupplierWeek();
        dayAmount[day] += amount;
        dayCount[day] += 1;
        supplierWeekAmount[supplierId][week] += amount;
    }

    function _checkPayee(bytes32 billId, bytes32 supplierId) internal view returns (Payee memory p) {
        if (billUsed[billId]) revert BillAlreadyPaid();
        p = payees[supplierId];
        if (!p.exists || nowSeconds() < p.activeAt) revert PayeeNotActive();
        if (p.frozen) revert PayeeIsFrozen();
    }

    function _send(bytes32 billId, bytes32 supplierId, Payee memory p, uint256 amount, bool autonomous) internal {
        billUsed[billId] = true;
        paid[billId] = Paid(supplierId, amount, autonomous);
        if (p.rail == Rail.Token) {
            token.safeTransfer(p.wallet, amount);
        } else {
            // The bank pays off-chain; the vault records the payment under the same checks.
            bytes32 ref = keccak256(abi.encode(billId, supplierId, amount, block.number));
            token.safeTransfer(owner, amount);
            emit BankPaymentRecorded(billId, supplierId, amount, ref);
        }
    }
}
