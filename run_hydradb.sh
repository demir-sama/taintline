#!/usr/bin/env bash
# Start a local single-node HydraDB (plaintext, dev only). Usage: HYDRADB_BIN=path ./run_hydradb.sh
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p .hydradb/store .hydradb/cache
[ -f .hydradb/auth-token ] || { python3 -c "import secrets;print(secrets.token_hex(24))" > .hydradb/auth-token; chmod 600 .hydradb/auth-token; }
export CLOUD_PROVIDER=local LOCAL_PATH="$PWD/.hydradb/store" GRAPH_NAMESPACE=default GRAPH_ID=default \
  GRAPH_CELL_ID=cell-0 GRAPH_CELLS=cell-0 GRAPH_NODE_ID=node-0 \
  GRAPH_BOLT_NODE_ADDRESSES=node-0=127.0.0.1:7687 GRAPH_ADVERTISED_BOLT_ADDR=127.0.0.1:7687 \
  GRAPH_DATA_CACHE_DIR="$PWD/.hydradb/cache" GRAPH_AUTH_TOKEN_FILE="$PWD/.hydradb/auth-token" \
  GRAPH_ALLOW_PLAINTEXT=true RUST_MIN_STACK=33554432 RUST_LOG=${RUST_LOG:-warn}
exec "${HYDRADB_BIN:-graph-node}"
