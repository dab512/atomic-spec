---
id: DOMAIN-USECASE-001
type: use-case
parent: DOMAIN
title: "Название бизнес-сценария"
status: draft
change_class: additive
change_type: RuleChange
actors: []
emits: []
consumes: []
owners:
  analyst: ""
  developer: ""
  tester: ""
created: YYYY-MM-DD
updated: YYYY-MM-DD
---

## Intent

Опишите актора, цель, результат успеха и последствия отказа.

## Domain Rules

### DR-1. Название правила

Условие, обязательное поведение, границы и последствия нарушения.

## Acceptance Criteria

### AC-1. Успех

Проверяет DR-1.

```gherkin
Scenario: Бизнес-результат
  Given конкретное исходное состояние
  When актор выполняет действие
  Then наблюдается определённый результат
```

### AC-2. Отказ

Проверяет DR-1.

```gherkin
Scenario: Нарушено условие
  Given состояние за допустимой границей
  When актор выполняет действие
  Then наступает определённый отказ
    And сохраняется требуемый инвариант
```

## Business Model

Предметные понятия, отношения, бизнес-события и инварианты.

## Constraints

Измеримые гарантии потребителю. Обязательные проверяемые гарантии объявляйте
как DR/BR с устойчивым ID; здесь допускаются ссылки и контекст.

## Open Questions

Нет / OQ-N с blocking или non-blocking и явным допущением.

## Decision Log

DL-N, дата, бизнес-решение и обоснование.
