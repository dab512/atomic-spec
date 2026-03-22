---
id: METH
type: domain
parent: ATOMICSPEC
title: "Домен: Методология Atomic Spec"
status: active
implementation:
  status: done
verification:
  status: passed
tags: [methodology, core]
created: 2024-01-01
updated: 2026-03-23
---

## Intent

Домен Methodology описывает внутренние процессы методологии Atomic Spec: как создаются атомы, как работает пайплайн ролей, как проходит gate-валидация. Это мета-уровень — методология описывает сама себя.

## Domain Rules

- **DR-1:** Каждый процесс методологии описан атомом того же формата, что и бизнес-требования
- **DR-2:** Мета-спецификации следуют тем же правилам gate-валидации
- **DR-3:** Изменения в методологии проходят полный пайплайн Аналитик → Разработчик → Тестировщик

## Bounded Context

- Lifecycle management — управление жизненным циклом атомов
- Role coordination — координация ролей и переключений между ними
- Quality gates — контроль качества на переходах между ролями
