#!/usr/bin/env bash
# Local FISCO BCOS v3.17.1 chain (Air, four nodes, non-SM) for the payables agent.
#   chain/fisco/fisco.sh up      download (once), build (once) and start the chain; web3 RPC on 127.0.0.1:8546
#   chain/fisco/fisco.sh down    stop the nodes
#   chain/fisco/fisco.sh reset   stop, delete the chain data, build a fresh chain
# The chain lives in $FISCO_HOME (default ~/fisco-chain): the official builder script breaks on paths with spaces.
set -euo pipefail
VERSION=v3.17.1
SHA256=9c7a7524b43f2f2354b0aacd32b921caeafc3472837d16b3bccd164a5bd1a4f4   # fisco-bcos-macOS-arm.tar.gz
D="${FISCO_HOME:-$HOME/fisco-chain}"
NODES="$D/nodes/127.0.0.1"

fetch() {
  mkdir -p "$D/home"
  if [ ! -x "$D/fisco-bcos" ]; then
    case "$(uname -s)-$(uname -m)" in
      Darwin-arm64) ASSET=fisco-bcos-macOS-arm.tar.gz ;;
      Darwin-x86_64) ASSET=fisco-bcos-macOS-x86_64.tar.gz ;;
      Linux-x86_64) ASSET=fisco-bcos-linux-x86_64.tar.gz ;;
      *) echo "unsupported platform"; exit 1 ;;
    esac
    curl -fsSL --retry 2 -o "$D/$ASSET" "https://github.com/FISCO-BCOS/FISCO-BCOS/releases/download/$VERSION/$ASSET"
    if [ "$ASSET" = fisco-bcos-macOS-arm.tar.gz ]; then echo "$SHA256  $D/$ASSET" | shasum -a 256 -c -; fi
    tar -xzf "$D/$ASSET" -C "$D"
  fi
  [ -f "$D/build_chain.sh" ] || curl -fsSL -o "$D/build_chain.sh" "https://raw.githubusercontent.com/FISCO-BCOS/FISCO-BCOS/$VERSION/tools/BcosAirBuilder/build_chain.sh"
}

build() {
  (cd "$D" && HOME="$D/home" bash build_chain.sh -v "$VERSION" -p 30300,20200 -l 127.0.0.1:4 -o nodes -e ./fisco-bcos)
  # Web3 JSON-RPC on node0 only, loopback, port 8546 (8545 is left for Hardhat).
  python3 - "$NODES/node0/config.ini" <<'PY'
import sys
p = sys.argv[1]; s = open(p).read()
s = s.replace("[web3_rpc]\n    enable=false\n    listen_ip=0.0.0.0\n    listen_port=8545",
              "[web3_rpc]\n    enable=true\n    listen_ip=127.0.0.1\n    listen_port=8546")
open(p, "w").write(s)
PY
}

case "${1:-up}" in
  up)
    fetch
    [ -d "$NODES/node0" ] || build
    bash "$NODES/start_all.sh"
    for i in $(seq 1 30); do
      curl -s -H 'Content-Type: application/json' --data '{"jsonrpc":"2.0","method":"eth_chainId","params":[],"id":1}' http://127.0.0.1:8546 >/dev/null && break
      sleep 1
    done
    echo "FISCO BCOS web3 RPC on http://127.0.0.1:8546 (chain id 20200)"
    ;;
  down) [ -d "$NODES" ] && bash "$NODES/stop_all.sh" || true ;;
  reset)
    [ -d "$NODES" ] && bash "$NODES/stop_all.sh" || true
    rm -rf "$D/nodes"
    fetch && build && bash "$NODES/start_all.sh"
    ;;
  *) echo "usage: $0 up|down|reset"; exit 1 ;;
esac
