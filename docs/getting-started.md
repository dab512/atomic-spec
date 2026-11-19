English | [Русский](ru/getting-started.md)

# Getting started

1. Read project instructions and related atoms. Use its registry and permitted
   search; determine spec-root, scope, revision and the configured Guard.
2. Copy the business template to your specs directory, assign a stable ID and
   register `ID → repository-relative path` in `specs/registry.json`.
3. Describe the business contract and pass Gate A. Reuse existing architecture;
   add a standalone architecture atom only when a new decision is needed.
4. Write AC headings and Gherkin; pass Gate B and obtain required project approval.
5. Write behavioral tests with simultaneous requirement annotations. Run them and
   record the expected RED before implementation (Gate C).
6. Implement with business/architecture references; pass the same tests and affected
   regressions (Gate D). Complete the project-required acceptance.

## Install the skill

```sh
apm install dab512/atomic-spec --target agent-skills
```

For a pinned, independently extractable copy, download the release asset
`atomic-spec-orchestrator-2.0.0.zip` from the GitHub v2.0.0 release and extract it
into `.agents/skills/`. Its top-level directory is `atomic-spec-orchestrator`.
APM compatibility is retained; a live APM service installation is not part of the
local archive acceptance.

The bundled Git Guard is used only when the project has no configured instance.
Python/JSON audit needs Python 3.11+. Node/Go dependencies are prepared explicitly
with `bash .agents/skills/atomic-spec-orchestrator/scripts/setup-guard.sh`.
Read the skill's references/specguard.md before invoking it.


[Methodology](methodology.md) · [Gates](gate-validation.md) · [Migration to 2.0](migration-v2.md)
