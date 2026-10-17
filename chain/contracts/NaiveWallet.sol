// SPDX-License-Identifier: MIT
pragma solidity ^0.8.11;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

/// @title NaiveWallet
/// @notice Baseline for the demo (task 8): an agent wallet with no rules. The agent key can send
/// any amount to any address. Never use this outside the side-by-side demo.
contract NaiveWallet {
    using SafeERC20 for IERC20;

    IERC20 public immutable token;
    address public immutable agent;

    event Sent(address indexed to, uint256 amount, string memo);

    constructor(IERC20 token_, address agent_) {
        token = token_;
        agent = agent_;
    }

    function send(address to, uint256 amount, string calldata memo) external {
        require(msg.sender == agent, "not agent");
        token.safeTransfer(to, amount);
        emit Sent(to, amount, memo);
    }
}
