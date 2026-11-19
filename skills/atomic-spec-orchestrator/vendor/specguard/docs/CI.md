# Подключение Guard к CI приложения

[CI самого инструмента](../.github/workflows/check.yml) проверяет его регрессии
и собственную разметку. Для проверки приложения нужен отдельный вызов против
его checkout, политики и спецификаций. Никакого изменения CI приложения
инструмент автоматически не делает.

Пример для GitHub pull request (все пути принадлежат приложению):

```yaml
name: requirements
on: pull_request
permissions:
  contents: read
jobs:
  traceability:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          fetch-depth: 0
          ref: ${{ github.event.pull_request.head.sha }}
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          repository: dab512/atomic-spec-guard
          # Replace with a reviewed full commit SHA of Guard; do not leave this placeholder.
          ref: PINNED_GUARD_COMMIT_SHA
          path: .tools/atomic-spec-guard
          persist-credentials: false
      - uses: actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0 # v7.1.0
        with:
          python-version: '3.11'
      - uses: actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1 # v7.1.0
        with:
          node-version: '20'
      - uses: actions/setup-go@d8cbb8045d7f43706b9177cceb36c1f91a6644d5 # v7.1.0
        with:
          go-version: '1.22.x'
          cache: false
      - run: npm ci --prefix .tools/atomic-spec-guard --ignore-scripts
      - name: Build parser
        working-directory: .tools/atomic-spec-guard
        run: GO111MODULE=off GOTOOLCHAIN=local go build -o goparser/goparser ./goparser
      - name: Check exact PR revisions
        env:
          BASE_SHA: ${{ github.event.pull_request.base.sha }}
          HEAD_SHA: ${{ github.event.pull_request.head.sha }}
        run: |
          python3 .tools/atomic-spec-guard/specguard.py check \
            --root "$GITHUB_WORKSPACE" \
            --config specs/atomic-spec-guard.yaml --spec-root specs --scope src \
            --base "$BASE_SHA" --revision "$HEAD_SHA" \
            --json --output specguard-report.json
```

Замените `PINNED_GUARD_COMMIT_SHA` проверенным SHA из
[истории Guard](https://github.com/dab512/atomic-spec-guard/commits/main),
а `src/specs` — путями проекта. Сохраняйте code, config, registry и spec
в одном репозитории: `--revision` читает их из одной ревизии Git.
Если политика хранится снаружи checkout, положите её в репозиторий приложения;
ревизионный режим не читает внешние файлы вместо зафиксированной политики.

Для push используйте явные event.before/event.after SHA. При первом push
нулевого before SHA нет в истории; задайте согласованную базу или выполните
`audit` всей нужной области. Не заменяйте неизвестную базу HEAD ради PASS.
При необходимости проверки только изменений ветки вычислите её merge-base с
целевой веткой. Политика и требования должны существовать в проверяемой ревизии.

Для локальной проверки незакоммиченных файлов используйте `--working-tree`.
Для зафиксированного diff этот флаг не нужен. Для Markdown-ссылок добавьте
`--repository-url https://github.com/OWNER/REPOSITORY`; JSON содержит точные
координаты и SHA без этой настройки.

Guard не исполняет анализируемый исходник, но политика PR может менять область
проверки. Ревью изменений самой политики/спецификации остаётся обязательным
решением команды. Не запускайте PR с секретами через `pull_request_target`.
