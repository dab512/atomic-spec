#!/usr/bin/env bash
# atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-18
# Ошибка проверки останавливает вызов до запуска сервисов; скрипт не управляет стендом.
set -euo pipefail
sg_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
sg_python="${SPECGUARD_PYTHON:-python3}"
sg_base_args=(--local-enforcement)
if [ -n "${SPECGUARD_BASE:-}" ]; then
    sg_base_args+=(--base "$SPECGUARD_BASE")
fi
"$sg_python" "$sg_dir/specguard.py" check --working-tree "${sg_base_args[@]}" \
    --scope "${SPECGUARD_SCOPE:-.}" \
    --config "${SPECGUARD_CONFIG:-specs/atomic-spec-guard.yaml}" \
    --spec-root "${SPECGUARD_SPEC_ROOT:-specs}" \
    --node "${SPECGUARD_NODE:-node}" \
    --node-modules "${SPECGUARD_NODE_MODULES:-$sg_dir/node_modules}" "$@"
