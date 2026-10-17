// SPDX-License-Identifier: MIT
pragma solidity ^0.8.11;

interface IBondPool {
    function lock(bytes32 billId, uint256 amount, uint256 r, uint8 mode) external;
    function recoverable(bytes32 billId) external view returns (uint256);
    function recordRecovery(bytes32 billId, uint256 amount) external;
}
