#!/usr/bin/env bash
# atomic-spec://ATOMIC-GUARD-001/DR-20
# Локальный аудит использует собственные manifest и спеку, не включая контроль аннотаций в CI приложения.
set -euo pipefail
sg_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$sg_dir"
sg_tmp=$(mktemp -d)
trap 'rm -rf "$sg_tmp"' EXIT
if [ -z "${SPECGUARD_GO_PARSER:-}" ]; then
    export SPECGUARD_GO_PARSER="$sg_tmp/goparser"
    GO111MODULE=off GOTOOLCHAIN=local "${SPECGUARD_GO:-go}" build -o "$SPECGUARD_GO_PARSER" ./goparser
fi
"${SPECGUARD_PYTHON:-python3}" selfcheck.py "$@"
