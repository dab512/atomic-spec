# Atomic Spec Guard

[![CI](https://github.com/dab512/atomic-spec-guard/actions/workflows/check.yml/badge.svg)](https://github.com/dab512/atomic-spec-guard/actions/workflows/check.yml)

Детерминированная проверка связей исходного кода с требованиями
[Atomic Spec](https://github.com/dab512/atomic-spec).
Методология и шаблоны — в **[dab512/atomic-spec](https://github.com/dab512/atomic-spec)**,
её документация — на [dab512.github.io/atomic-spec](https://dab512.github.io/atomic-spec/).
Этот репозиторий содержит отдельный инструмент: CLI, парсеры, политику и тесты.

Guard находит настоящие комментарии `atomic-spec://SPEC-ID/DR-N`, проверяет
реестр, существование требования и покрытие блоков по выбранной политике.
Он собирает контекст для агента, показывает места использования требования и
выгружает пояснения для ревью. Анализ не вызывает LLM, не обращается к сети
и не исполняет проверяемые исходники.

Поддерживаются Python, Go, JS/TS/JSX/TSX и YAML. Нужны Git, Python **3.11+**,
Node.js **20+**; для Go-исходников и полного набора тестов — Go **1.22+**.
Arcadia, ya, SkillStore, TOne, БД и сервисы для запуска не нужны.
Подготовка зависимостей требует доступа к PyPI/npm; сам анализ работает локально.

## Установка из Git

```sh
git clone https://github.com/dab512/atomic-spec-guard.git
cd atomic-spec-guard
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
npm ci --ignore-scripts
GO111MODULE=off GOTOOLCHAIN=local go build -o goparser/goparser ./goparser
```

Запускайте `python3 specguard.py`; публикация пакета в PyPI/npm не требуется.
Python использует стандартную библиотеку; requirements-dev.txt нужен для линтера.
TypeScript и YAML закреплены в package-lock.json. Команды ниже рассчитаны на
macOS/Linux/WSL с Bash. Для собственного Python-only проекта без YAML-политики
Node/Go не требуются; для рекомендуемой YAML-политики нужен Node.

## Проверить установку

```sh
bash scripts/check.sh
bash scripts/self-check.sh
```

Первая команда запускает Ruff, проверку синтаксиса JS, Go tests/vet и все
Python/CLI-регрессии с настоящими парсерами. Вторая проверяет исходники самого
Guard по собственной спецификации и явному manifest. Отсутствие зависимости
завершает проверку ошибкой. Эти команды выполняются и в GitHub Actions.

## Попробовать на отдельном проекте

В [examples/minimal](examples/minimal) есть небольшой проект без сервисов:
спецификация, реестр, политика и исходники на четырёх языках.
Из каталога Guard:

```sh
python3 specguard.py audit --root examples/minimal \
  --config specs/atomic-spec-guard.yaml --directory src --explain
python3 specguard.py getcontext brief --root examples/minimal \
  --config specs/atomic-spec-guard.yaml --files src/fare.py
python3 specguard.py whereused --root examples/minimal \
  --config specs/atomic-spec-guard.yaml --directory src \
  --spec atomic-spec://DEMO-FARE/DR-1
python3 specguard.py comments --root examples/minimal \
  --config specs/atomic-spec-guard.yaml --directory src
```

Ожидается exit code 0 и `complete: True` (в JSON — `true`).
`whereused` показывает вхождения только внутри выбранного `src`.
[Инструкция примера](examples/minimal/README.md) объясняет отрицательную проверку.
Автотесты повторяют пример в изолированной временной копии, портят URI,
проверяют отказ и восстановление.

## Подключить свой проект

1. Возьмите структуру [examples/minimal](examples/minimal): `specs/registry.json`,
   `specs/*.spec.md` и `specs/atomic-spec-guard.yaml`. Реестр — объект
   `ID → путь от корня проекта`, ID совпадает с frontmatter спецификации.
2. Используйте существующие DR/BR/AC своей спецификации. Ссылка должна объяснять
   поведение конкретного блока:

   ```python
   # atomic-spec://DEMO-FARE/DR-1
   # Минимальная стоимость не опускается ниже согласованного тарифа.
   def minimum_fare():
       return 100
   ```

3. Запустите инструмент против своего checkout:

   ```sh
   python3 /path/to/atomic-spec-guard/specguard.py audit \
     --root /path/to/project --config specs/atomic-spec-guard.yaml \
     --directory src --explain
   ```

4. Адаптируйте правила и severity по [CONFIGURATION.md](CONFIGURATION.md).
   Начальный профиль проверяет функции/типы/самостоятельные тестовые сценарии,
   но не является готовой матрицей прав вашего приложения.
5. Подключите такую же явную команду к своему build/CI.
   [Пример GitHub Actions](docs/CI.md) использует точные base/head SHA.

`--root` — checkout проверяемого проекта. Пути `--config`, `--files`,
`--directory`, `--scope`, `--spec-root` и пути реестра считаются от него.
По умолчанию `--spec-root specs`, `--scope .`; политика включается явным `--config`.
Парсеры берутся из установки Guard, а не из зависимостей проверяемого приложения.
Если Go-бинарник лежит отдельно, передайте `--go-parser /path/to/binary`.
Для JS/YAML можно явно задать `--node` и `--node-modules`.

## Проверка изменений Git

Из checkout проверяемого проекта:

```sh
# Все изменения ветки и текущие staged/unstaged/untracked изменения.
python3 /path/to/atomic-spec-guard/specguard.py check \
  --config specs/atomic-spec-guard.yaml --scope src \
  --base BASE_SHA --working-tree

# Зафиксированные ревизии: код, политика и требования читаются из REVISION_SHA.
python3 /path/to/atomic-spec-guard/specguard.py check \
  --config specs/atomic-spec-guard.yaml --scope src \
  --base BASE_SHA --revision REVISION_SHA \
  --repository-url https://github.com/OWNER/REPOSITORY
```

`BASE_SHA` и `REVISION_SHA` замените реальными SHA. Репозиторий должен иметь
историю обоих коммитов. `--base HEAD --working-tree` проверяет только текущие
незакоммиченные изменения; он не проверяет предыдущие коммиты ветки.
`--local-enforcement` использует `local_enforcement.base_ref` политики через
`git merge-base`; неизвестная база — ошибка без fallback.
`scripts/local-check.sh` — обёртка для этого режима; переменные
`SPECGUARD_CONFIG`, `SPECGUARD_SPEC_ROOT`, `SPECGUARD_SCOPE`, `SPECGUARD_BASE`
позволяют задать свои пути и базу.

`--pr` в Git-адаптере отклоняется: передавайте base/head SHA из вашего CI.
`--repository-url` задаёт HTTPS URL GitHub для ссылок на точную ревизию;
без него историческая локация содержит путь и SHA без придуманного URL.

## Команды и результаты

| Команда | Назначение |
|---|---|
| `audit` | Проверить выбранные файлы или каталог |
| `check` | Проверить изменения относительно явной базы |
| `getcontext brief/full` | Требования либо документы, связанные с кодом |
| `whereused --spec URI` | Места использования требования в выбранной области |
| `comments brief/full` | Пакет комментариев и требований для смыслового ревью |

`--json` выдаёт машинный отчёт, `--output FILE` сохраняет его,
`--explain` показывает применение правил. Кеш включается через
`--cache-dir DIR`; `--no-cache` его обходит. `comments` всегда делает свежий анализ.

| Exit code | Значение |
|---|---|
| 0 | В выбранной области нет errors; warnings допустимы |
| 1 | Нарушения или неполный анализ |
| 2 | Ошибка аргументов, конфигурации или инфраструктуры |

Формальный PASS не доказывает смысловую правильность реализации, полноту
бизнес-логики или прохождение тестов приложения. Смысл связей проверяет ревьюер.
Bash, JSON и другие неподдерживаемые форматы явно исключаются; AST-покрытие
для них не заявляется. Ссылки внутри строк/docstring не считаются аннотациями.
Directory-режим ограничен по объёму, не следует symlink и пропускает зависимости.
Изменения rename/copy требуют явной нормализации; произвольные пути с табами
и переводами строк не поддерживаются. Git SHA-256 repositories пока не поддержаны.

## Документация и происхождение

- [Настройка политики](CONFIGURATION.md)
- [Разметка кода](AGENT_GUIDE.md)
- [Связи и контекст](TRACEABILITY.md)
- [Подключение к CI](docs/CI.md)
- [Спецификация самого Guard](spec/guard.spec.md)
- [Происхождение и изменения при выделении](PATCHES.md)

Исторические ID `SKSTORE-*` и fixtures сохранены для совместимости и регрессий;
для вашего проекта выбирайте свои ID. Manifest исходного снимка —
[UPSTREAM.json](UPSTREAM.json); он фиксирует вход импорта, а не хеши текущей версии.
MIT, см. [LICENSE](LICENSE).
