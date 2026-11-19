---
id: ARCH-GUARD-001
type: use-case
parent: ARCHITECTURE
title: "Зафиксированный Git Guard"
status: ready
change_class: breaking
change_type: FlowChange
created: 2026-11-19
updated: 2026-11-19
---

## Intent

Зафиксированный Git Guard. Требования описывают наблюдаемый контракт методологии Atomic Spec 2.0.

## Domain Rules

### DR-1. Версия

Git Guard поставляется из commit 34c096ef1ac8cebdc042647572f111ffcda9fa72 репозитория dab512/atomic-spec-guard. Поставка применяет нейтральные имена и namespace требований; исходная ревизия, адаптация и SHA-256 поставляемых файлов фиксируются отдельно.

### DR-2. Подготовка

Для Python/JSON достаточно Python 3.11+. Node 20+ нужен для JS/TS/YAML, Go 1.22+ — для Go. Явный setup готовит зависимости в выбранном кеше; обычный launcher ничего не скачивает.

### DR-3. Ревизии

Git diff использует точные base/revision; --working-tree включает сохранённые изменения. --pr отклоняется. Политика/реестр/требования читаются из проверяемой ревизии.

## Acceptance Criteria

### AC-1. Независимая установка

```gherkin
Scenario: Независимая установка
  Given скилл извлечён во временный каталог без репозитория донора
  When launcher выполняет Python audit с JSON-политикой
  Then реальная ссылка разрешается без Git и без скачивания зависимостей
```

### AC-2. Повреждение поставки

```gherkin
Scenario: Повреждение поставки
  Given изменён файл vendored Guard
  When проверяется manifest происхождения
  Then сборка релиза отказывает
```

## Requirements Served

atomic-spec://METH-TRACE-010/DR-2
atomic-spec://METH-TRACE-010/DR-3

## Alternatives and Replacement

Проектный экземпляр приоритетен. Поставляемая версия заменяется явным обновлением commit и manifest с регрессиями; Git-адаптер не подменяется Git-адаптером автоматически.

## Decision Log

DL-2026-11-19: редакция 2.0 меняет порядок gates и разделяет бизнес-контракт и архитектуру.
Предыдущая редакция сохранена в Git commit 594a44f0f8c8916faf96a3c13e3247e83b7ae2d3.
Существующие ID требований сохраняют предмет ссылки; изменение контракта отмечено breaking.
