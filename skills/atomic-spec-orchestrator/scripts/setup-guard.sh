#!/usr/bin/env bash
# Explicit preparation only; normal analysis never installs dependencies.
set -euo pipefail
skill_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
sg_cache=${ATOMIC_SPEC_CACHE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/atomic-spec-orchestrator}
command -v python3 >/dev/null
command -v node >/dev/null
command -v npm >/dev/null
command -v go >/dev/null
python3 -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required"'
node -e 'if (Number(process.versions.node.split(".")[0]) < 20) process.exit(1)'
mkdir -p "$sg_cache/node" "$sg_cache/go-build"
cp "$skill_dir/vendor/specguard/package.json" "$skill_dir/vendor/specguard/package-lock.json" "$sg_cache/node/"
npm ci --ignore-scripts --prefix "$sg_cache/node" --cache "$sg_cache/npm-cache" --no-audit --no-fund
(
  cd "$skill_dir/vendor/specguard"
  GOCACHE="$sg_cache/go-build" GO111MODULE=off GOTOOLCHAIN=local go build -o "$sg_cache/goparser" ./goparser
)
printf 'Spec Guard dependencies ready: %s\n' "$sg_cache"
