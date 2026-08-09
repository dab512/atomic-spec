# Atomic Spec — AI Agent Skill

Канонический способ установки:

```bash
apm install svetlyak40wt/atomic-spec --target agent-skills
```

APM установит bundle из `skills/atomic-spec-orchestrator/` в `.agents/skills/atomic-spec-orchestrator/`.

## Ручная установка

Если нужен legacy-способ без APM, скопируйте содержимое `skill/` или `skills/atomic-spec-orchestrator/` в директорию скиллов вашего агента.

## Использование

Скилл активируется автоматически когда вы:
- Просите спроектировать фичу или написать требования
- Декомпозируете задачу на атомы
- Работаете с файлами в директории `/specs/`
- Упоминаете "атом", "спек", "Atomic Spec", "domain rules", "acceptance criteria"

## Роли

Скилл переключается между тремя ролями:
- **Аналитик** — бизнес-требования, DR, AC
- **Разработчик** — Tech Spec, код, API
- **Тестировщик** — Test Plan, тесты, покрытие
