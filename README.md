English | [Русский](README.ru.md)

# Atomic Spec 2.0

Portable business requirements, replaceable architecture, executable tests before implementation.

The specification must be sufficient to reproduce the business functionality without
reading the old code. One atom is one `*.spec.md` with a stable ID. Business domains
are independent of the stack; `architecture/` records implementation decisions and constraints.

**Workflow:** analysis **A** → Gherkin **B** → executable tests **C / RED** →
implementation **D / GREEN** → acceptance. One agent or a team can perform the roles;
delegation is optional.
## Installation

```sh
apm install dab512/atomic-spec --target agent-skills
```

Pinned distribution: [GitHub Release v2.0.1](https://github.com/dab512/atomic-spec/releases/tag/v2.0.1), asset `atomic-spec-orchestrator-2.0.1.zip`. Extract into `.agents/skills/`.

## Getting started

1. Read project instructions and related atoms through the registry.
2. Start with the [business template](templates/atom-template.spec.md), assign and register its ID.
3. Describe the contract; capture a new independent decision in an [architecture atom](templates/architecture-template.spec.md).
4. Pass A/B, write and run RED tests before behavior, then implement GREEN.
5. Complete acceptance, update references and record evidence with scope/revision.

Add `atomic-spec://SPEC-ID/DR-N` comments with explanations while creating code
and independent tests. A configured project Guard takes priority. Otherwise a pinned
[Atomic Spec Guard](https://github.com/dab512/atomic-spec-guard) is bundled.
Formal PASS does not establish business correctness; see [verification limits](docs/traceability.md).

## Documentation

- [Методология / Methodology](docs/methodology.md)
- [Роли / Roles](docs/roles-and-pipeline.md)
- [Gates](docs/gate-validation.md)
- [Формат атома / Atom anatomy](docs/atom-anatomy.md)
- [Архитектура и перенос / Architecture](docs/architecture.md)
- [Трассируемость / Traceability](docs/traceability.md)
- [Изменения / Change classification](docs/change-types.md)
- [VCS](docs/git-conventions.md)
- [Правки / Amendments](docs/amendments.md)
- [Миграция 2.0 / Migration](docs/migration-v2.md)

## Development and verification

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
python -m playwright install chromium
ATOMIC_SPEC_CACHE_DIR="$PWD/.local/guard-cache" bash skills/atomic-spec-orchestrator/scripts/setup-guard.sh
python tools/release.py check
python tools/release.py build
```

The check command validates links, registry, Guard provenance, real extracted-skill
journeys and page geometry. Missing dependencies and skips are not PASS.
Normative atoms are indexed in [specs/registry.json](specs/registry.json).
[Website](https://dab512.github.io/atomic-spec/) · [Release changes](CHANGELOG.md) · [MIT](LICENSE).

For an installed Chrome, set ATOMIC_SPEC_BROWSER to its full path; GitHub CI uses the hosted runner Chrome.
