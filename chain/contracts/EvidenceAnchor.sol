// SPDX-License-Identifier: MIT
pragma solidity ^0.8.11;

/// @title EvidenceAnchor
/// @notice Append-only daily Merkle roots of the decision log (plan section 7.4).
contract EvidenceAnchor {
    address public immutable anchorer;
    mapping(uint256 => bytes32) public roots;

    event Anchored(uint256 indexed day, bytes32 root);

    constructor(address anchorer_) {
        require(anchorer_ != address(0), "zero address");
        anchorer = anchorer_;
    }

    function anchor(uint256 day, bytes32 root) external {
        require(msg.sender == anchorer, "not anchorer");
        require(roots[day] == bytes32(0), "day already anchored");
        require(root != bytes32(0), "empty root");
        roots[day] = root;
        emit Anchored(day, root);
    }
}
