#!/usr/bin/env bash
# local-dev.sh — единый orchestrator local-dev окружения skillstore.
#
# Запускает в одном foreground-процессе:
#   - PostgreSQL (системный — должен быть поднят отдельно или через init-pg.sh)
#   - pgmigrate (миграции)
#   - passport-mock (port 8090)
#   - idm-mock (port 8091)
#   - abc-mock (port 8095)
#   - backend skillstore (port 8080)
#   - frontend vite dev (port 5173)
#   - Caddy на 443 с TLS (через mkcert), реверс-прокси на https://skillstore.local.yandex-team.ru/
#   - /etc/hosts: 127.0.0.1 skillstore.local.yandex-team.ru
#
# Live keypress-controls (без выхода из скрипта):
#   D — переключить на LOCAL DEV (трафик в локальный backend+frontend)
#   T — переключить на TESTING  (трафик в реальный Yandex testing-кластер)
#   R — restart backend (rebuild cmd/app + start)
#   X — reset data: TRUNCATE PG + очистить MinIO bucket (с y/N подтверждением)
#   S — статус всех компонентов
#   V — verify (DNS / TLS / RTT / hostname)
#   Q — выйти и снять оверрайд (Ctrl+C тоже работает)
#
# При SIGINT/SIGTERM/EXIT скрипт автоматически снимает все оверрайды:
#   - убирает /etc/hosts entry
#   - останавливает caddy (sudo)
#   - останавливает все child процессы (mocks, backend, frontend)
#
# Использование:
#   bash services/local-dev/scripts/local-dev.sh                # дефолтные порты
#   bash services/local-dev/scripts/local-dev.sh --port 8100    # весь стенд от 8100
#   SKILLSTORE_PORT_BASE=8100 bash .../local-dev.sh             # то же через env
#   bash .../local-dev.sh --port 8100 --skip-atomic-spec-guard             # без atomic-spec-guard на этот запуск
#   bash .../local-dev.sh --check-specs                       # только проверка, без сервисов
# Без --port старт проверяет, что дефолтные порты свободны (наши остатки снимает,
# на чужой процесс не покусится — подскажет --port). SKILLSTORE-104.
#
# Зависимости (одноразово): bash services/local-dev/scripts/local-dev.sh install-deps
set -uo pipefail

# atomic-spec://SKSTORE-SPEC-TRACE-001/DR-18
# Ошибка покрытия должна остановить запуск до сервисных действий; установка зависимостей остаётся доступной для подготовки проверки.
LOCAL_SPECGUARD="${SPECGUARD_LOCAL_ENTRYPOINT:-/not-used}"
LOCAL_SKIP_SPECS=0
LOCAL_CHECK_SPECS_ONLY=0
for local_arg in "$@"; do
    case "$local_arg" in
        --skip-atomic-spec-guard) LOCAL_SKIP_SPECS=1 ;;
        --check-specs) LOCAL_CHECK_SPECS_ONLY=1 ;;
    esac
done
if [ "$LOCAL_SKIP_SPECS" = 1 ] && [ "$LOCAL_CHECK_SPECS_ONLY" = 1 ]; then
    echo "local-dev: --skip-atomic-spec-guard несовместим с --check-specs" >&2
    exit 2
fi

# atomic-spec://SKSTORE-SPEC-TRACE-001/DR-18
# Явное отключение действует на всю сессию стенда, включая пересборки; без этого выбора проверка обязательна.
check_local_specs() {
    if [ "$LOCAL_SKIP_SPECS" = 1 ]; then
        echo "local-dev: проверка atomic-spec-guard отключена (--skip-atomic-spec-guard)"
        return 0
    fi
    bash "$LOCAL_SPECGUARD"
}

if [ "${1:-}" != "install-deps" ]; then
    check_local_specs || exit $?
    if [ "$LOCAL_CHECK_SPECS_ONLY" = 1 ]; then
        exit 0
    fi
fi

# ───── Параметризация портов
# Historical preflight fixture only; no services are started.
restart_backend() {
    # atomic-spec://SKSTORE-SPEC-TRACE-001/DR-18
    # Ошибка покрытия новой правки не должна останавливать уже работающий backend.
    check_local_specs || return $?
    # Визуальный разделитель — легко найти границу между сессиями рестарта
    # в скролле tmux/terminal. Включает timestamp чтобы при просмотре скриншотов
    # / копировании логов в чат сразу было видно когда именно был рестарт.
    local _rb_ts
    _rb_ts=$(date '+%Y-%m-%d %H:%M:%S')
    printf '\n%s%s━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━%s\n' "$BOLD" "$YELLOW" "$RESET"
    printf '%s%s  ⟲ RESTART BACKEND  %s%s%s  %s%s\n' "$BOLD" "$YELLOW" "$RESET$DIM" "$_rb_ts" "$RESET" "$BOLD$YELLOW" "$RESET"
    printf '%s%s━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━%s\n' "$BOLD" "$YELLOW" "$RESET"

    log "${YELLOW}restart backend${RESET}: kill + rebuild + start..."
    # Глушим backend ПО НАШЕМУ ПОРТУ, а не pgrep по имени бинаря: при двух
    # стендах pgrep|head -1 попадал в первый попавшийся инстанс — R на одном
    # стенде рестартовал backend другого (SKILLSTORE-104).
    local pid
    pid=$(lsof -nP -iTCP:"$BACKEND_PORT" -sTCP:LISTEN -t 2>/dev/null | head -1)
    if [ -n "$pid" ]; then
        kill "$pid" 2>/dev/null || true
        # Wait for clean shutdown (max 5s)
        for _ in 1 2 3 4 5; do
            kill -0 "$pid" 2>/dev/null || break
            sleep 1
        done
        kill -9 "$pid" 2>/dev/null || true
    fi
    log "  билд cmd/app..."
    "$ARC_ROOT/ya" make "$SKILLSTORE_DIR/cmd/app" 2>&1 | tail -3

    # ya make иногда сносит symlink'и в deployment/config/generated/ (orphan-cleanup).
    # Без них backend упадёт: "platform_defaults.local.yaml: no such file or directory".
    # ensure_generated_configs пересоздаст через make update если файла нет.
    local platform_defaults="$SKILLSTORE_DIR/deployment/config/generated/config_vars.platform_defaults.local.yaml"
    if [ ! -e "$platform_defaults" ]; then
        log "  symlinks в generated/ пропали → make update (1-2 мин)..."
        (cd "$SKILLSTORE_DIR" && make update 2>&1 | tail -3)
    fi

    log "  старт..."
    cd "$SKILLSTORE_DIR"
    nohup ./cmd/app/app app \
        -c "$SKILLSTORE_DIR/config/config.yaml" \
        -p "$platform_defaults" \
        -f "$LOCAL_CONFIG_VARS" \
        > "$SERVICE_LOG" 2>&1 &
    CHILD_PIDS+=($!)
    if wait_endpoint "backend" "http://127.0.0.1:$BACKEND_PORT/ping" 30; then
        log "${GREEN}backend перезапущен${RESET}"
    else
        err "backend не поднялся, см. $SERVICE_LOG"
    fi
}
