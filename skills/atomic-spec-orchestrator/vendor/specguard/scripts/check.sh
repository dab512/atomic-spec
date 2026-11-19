#!/usr/bin/env bash
# atomic-spec://ATOMIC-GUARD-001/DR-16
# Локальная самопроверка обязательна перед отправкой изменений; отсутствие адаптера или зависимости не является успехом.
set -euo pipefail
cd "$(dirname "$0")/.."
sg_python="${SPECGUARD_PYTHON:-python3}"
sg_go="${SPECGUARD_GO:-go}"
sg_node="${SPECGUARD_NODE:-node}"
sg_ruff="${SPECGUARD_RUFF:-ruff}"
sg_tmp=$(mktemp -d)
trap 'rm -rf "$sg_tmp"' EXIT
export SPECGUARD_GO_PARSER="$sg_tmp/goparser"
export SPECGUARD_NODE="$sg_node"
export SPECGUARD_NODE_MODULES="${SPECGUARD_NODE_MODULES:-$PWD/node_modules}"
export RUFF_CACHE_DIR="$sg_tmp/ruff-cache"
"$sg_node" -e 'const p=process.env.SPECGUARD_NODE_MODULES;require(p+"/typescript");require(p+"/yaml")'
sg_sources=(specguard.py specguard_policy.py annotation_language.py annotation_uniqueness.py result_cache.py local_enforcement.py selfcheck.py tests/*.py pilot/run_comparison.py)
"$sg_ruff" check "${sg_sources[@]}"
"$sg_ruff" format --check "${sg_sources[@]}"
"$sg_node" --check parser.cjs
"$sg_node" --check policy.cjs
GO111MODULE=off GOTOOLCHAIN=local "$sg_go" build -o "$SPECGUARD_GO_PARSER" ./goparser
GO111MODULE=off GOTOOLCHAIN=local "$sg_go" test ./goparser
GO111MODULE=off GOTOOLCHAIN=local "$sg_go" vet ./goparser
"$sg_python" -m unittest discover -s tests -v
