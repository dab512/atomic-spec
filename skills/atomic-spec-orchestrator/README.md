# Atomic Spec Orchestrator 2.0.1

Read [SKILL.md](SKILL.md). Business and architecture templates are in assets/;
role guidance is in references/. This standalone archive contains the pinned Git
Guard sources, without node_modules, platform binaries or local caches.

Python/JSON audit works with Python 3.11+. Explicit setup for JS/TS/YAML/Go:
`bash scripts/setup-guard.sh`. A configured project Guard always takes priority;
do not run bundled setup or a second checker in such projects.

See [methodology and migration](https://github.com/dab512/atomic-spec/blob/v2.0.1/docs/migration-v2.md).
