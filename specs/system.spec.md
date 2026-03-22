---
id: ATOMICSPEC
type: system
title: "Atomic Spec — Методология живых требований"
status: active
implementation:
  status: done
verification:
  status: passed
owners:
  analyst: "community"
  developer: "community"
  tester: "community"
tags: [methodology, requirements, ddd, tdd]
created: 2024-01-01
updated: 2026-03-23
---

## Intent

Atomic Spec — это методология управления требованиями, в которой каждое требование живёт в отдельном файле (атоме), проходит через пайплайн из трёх ролей (Аналитик → Разработчик → Тестировщик) с gate-валидацией на каждом переходе, и хранит полную историю решений в git.

## Domain Rules

- **DR-1:** Один атом = один файл = одна единица знания. _Нарушение:_ потеря трассируемости.
- **DR-2:** Атом не удаляется — он устаревает (deprecated). _Нарушение:_ разрыв истории.
- **DR-3:** Gate перед каждым переходом роли. _Нарушение:_ артефакт передаётся без валидации.
- **DR-4:** Верхние секции атома технологически агностичны. _Нарушение:_ привязка бизнес-логики к платформе.
- **DR-5:** Каждое изменение домена требует явного решения в Decision Log. _Нарушение:_ немотивированные изменения.

## Domains

- **methodology** (atom-lifecycle, role-pipeline, gate-validation)
