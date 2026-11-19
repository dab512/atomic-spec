[English](README.md) | Русский

# Atomic Spec 2.0

Переносимые бизнес-требования, заменяемая архитектура и исполняемые тесты до реализации.

Спецификации должно хватать для воспроизведения всего бизнес-функционала без чтения
старого кода. Один атом — один `*.spec.md` с устойчивым ID. Бизнес-домены независимы
от стека; `architecture/` хранит решения и ограничения их реализации.

**Процесс:** аналитика **A** → Gherkin **B** → автотесты **C / RED** →
реализация **D / GREEN** → приёмка. Роли исполняет один агент или команда;
делегирование необязательно.
## Установка

```sh
apm install dab512/atomic-spec --target agent-skills
```

Закреплённая поставка: [GitHub Release v2.0.2](https://github.com/dab512/atomic-spec/releases/tag/v2.0.2), архив `atomic-spec-orchestrator-2.0.2.zip`. Распакуйте в `.agents/skills/`.

## Начало работы

1. Прочитайте правила проекта и связанные атомы через реестр.
2. Выберите [бизнес-шаблон](templates/atom-template.spec.md), задайте ID и зарегистрируйте его.
3. Опишите контракт; новое решение оформите [архитектурным атомом](templates/architecture-template.spec.md).
4. Пройдите A/B, напишите и запустите RED-тесты до поведения, затем реализуйте GREEN.
5. Выполните приёмку, актуализируйте ссылки и зафиксируйте доказательства со scope/revision.

Разметка `atomic-spec://SPEC-ID/DR-N` с пояснением создаётся одновременно с кодом
и самостоятельными тестами. Приоритетен проектный Guard. Для проектов без него
встроен закреплённый [Atomic Spec Guard](https://github.com/dab512/atomic-spec-guard).
Формальный PASS не доказывает бизнес-корректность; смотрите [границы проверки](docs/ru/traceability.md).

## Документация

- [Методология / Methodology](docs/ru/methodology.md)
- [Роли / Roles](docs/ru/roles-and-pipeline.md)
- [Gates](docs/ru/gate-validation.md)
- [Формат атома / Atom anatomy](docs/ru/atom-anatomy.md)
- [Архитектура и перенос / Architecture](docs/ru/architecture.md)
- [Трассируемость / Traceability](docs/ru/traceability.md)
- [Изменения / Change classification](docs/ru/change-types.md)
- [VCS](docs/ru/git-conventions.md)
- [Правки / Amendments](docs/ru/amendments.md)
- [Миграция 2.0 / Migration](docs/ru/migration-v2.md)

## Разработка и проверка

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
python -m playwright install chromium
ATOMIC_SPEC_CACHE_DIR="$PWD/.local/guard-cache" bash skills/atomic-spec-orchestrator/scripts/setup-guard.sh
python tools/release.py check
python tools/release.py build
```

Команда check проверяет ссылки, реестр, происхождение Guard, реальные сценарии
установки архива и геометрию страниц. Отсутствующие зависимости и skip не являются PASS.
Нормативные атомы — в [specs/registry.json](specs/registry.json).
[Сайт](https://dab512.github.io/atomic-spec/) · [Изменения релиза](CHANGELOG.md) · [MIT](LICENSE).

Для установленного Chrome задайте ATOMIC_SPEC_BROWSER полным путём к браузеру; GitHub CI использует Chrome образа runner.
