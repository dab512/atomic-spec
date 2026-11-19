#!/usr/bin/env bash
set -euo pipefail
skill_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
sg_cache=${ATOMIC_SPEC_CACHE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/atomic-spec-orchestrator}
sg_args=("${SPECGUARD_PYTHON:-python3}" "$skill_dir/vendor/specguard/specguard.py")
if [[ -d "$sg_cache/node/node_modules" ]]; then
  sg_args+=(--node-modules "$sg_cache/node/node_modules")
fi
if [[ -x "$sg_cache/goparser" ]]; then
  sg_args+=(--go-parser "$sg_cache/goparser")
fi
export PYTHONDONTWRITEBYTECODE=1
exec "${sg_args[@]}" "$@"
