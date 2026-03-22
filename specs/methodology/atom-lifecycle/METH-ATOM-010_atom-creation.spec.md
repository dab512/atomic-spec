---
id: METH-ATOM-010
type: use-case
parent: METH
title: "Жизненный цикл атома"
status: active
actors: [Analyst, Developer, Tester, Orchestrator]
emits: [AtomCreated, AtomActivated, AtomDeprecated]
consumes: []
tags: [lifecycle, atom, core]
implementation:
  status: done
verification:
  status: passed
created: 2024-01-01
updated: 2026-03-23
---

## Intent

Оркестратор или Аналитик создаёт новый атом (spec.md файл) для фиксации бизнес-требования. Атом проходит жизненный цикл: _draft/ (черновик с открытыми вопросами) → корень директории (активный, готов к разработке) → _deprecated/ (устаревший, заменён новым). На каждом этапе атом остаётся в файловой системе и git-истории.

## Domain Rules

- **DR-1:** Атом создаётся из шаблона atom-template.spec.md. _Нарушение:_ неполная структура, пропущенные секции.
- **DR-2:** Новый атом помещается в _draft/ пока есть открытые blocking-вопросы. _Нарушение:_ передача невалидированного требования в разработку.
- **DR-3:** Атом перемещается в корень директории когда все blocking OQ закрыты и Gate A пройден. _Нарушение:_ разработка по неготовому требованию.
- **DR-4:** Устаревший атом перемещается в _deprecated/ с указанием deprecated-by и причины. НИКОГДА не удаляется. _Нарушение:_ потеря истории решений.
- **DR-5:** Файл именуется по конвенции: DOMAIN-TYPE-NNN_slug.spec.md. _Нарушение:_ невозможность автоматической навигации.

## AC (Gherkin)

```gherkin
Scenario: Создание нового атома
  Given Аналитик получил бизнес-задачу
    And шаблон atom-template.spec.md доступен
  When Аналитик создаёт новый файл по шаблону с заполненным frontmatter
  Then файл помещён в _draft/ соответствующего домена
    And все секции Аналитика заполнены
    And id и именование файла соответствуют конвенции

Scenario: Активация атома (→ DR-3)
  Given атом находится в _draft/
    And все blocking OQ закрыты
    And Gate A пройден
  When Оркестратор перемещает атом в корень директории
  Then атом готов к передаче Разработчику
    And status в frontmatter = active

Scenario: Депрекация атома (→ DR-4)
  Given атом активен и заменён новым
  When Аналитик перемещает атом в _deprecated/
  Then поле deprecated-by указывает на замену
    And файл остаётся в git-истории
    And файл НЕ удаляется

Scenario: Попытка удалить атом (→ DR-4, negative)
  Given атом существует в любом статусе
  When кто-либо пытается удалить файл
  Then удаление запрещено
    And атом должен быть перемещён в _deprecated/
```

## DMT

- **Aggregate:** Atom (create, activate, deprecate)
- **Events:** AtomCreated, AtomActivated, AtomDeprecated
- **Invariants:** unique id, naming convention, no deletion

## Constraints

- **[SEC]** Атом не может быть удалён из git-истории (no force push on specs)
- **[IDMP]** Повторное создание атома с тем же id невозможно

## Decision Log

- **DL-1:** Файловая система как статус-машина (_draft/, root, _deprecated/). _Причина:_ статус виден без открытия файла.
- **DL-2:** YAML frontmatter для метаданных. _Причина:_ машинно-читаемый, удобный для git diff.

## Tech Spec

Filesystem-based state machine. No database required. Git provides history and audit trail.

## Implementation Notes

- **Trade-offs:** файловая система как state machine — простота vs. отсутствие транзакционности
- **Dependencies:** git, текстовый редактор, опционально AI-агент
- **Limitations:** нет автоматической валидации без CI/CD pipeline
