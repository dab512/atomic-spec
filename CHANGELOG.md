# Changelog

## 2.0.0 — 2026-11-19

Breaking methodology update based on atomic-spec-orchestrator 2.0.0-local.2.

- Portable business contracts and a replaceable architecture domain.
- Gates A (analysis), B (Gherkin), C (executable RED), D (GREEN), then acceptance.
- Requirement annotations created together with code and tests; stable IDs and registry.
- One canonical atom lifecycle; implementation claims scoped to actual acceptance.
- Independent compatibility class and change-type axes; project-defined VCS workflow.
- Business/architecture templates, bilingual documentation and updated static site.
- Git Guard pinned to 34c096ef1ac8cebdc042647572f111ffcda9fa72, isolated archive smoke tests.

[Migration guide](docs/migration-v2.md). The historical methodology remains in
[594a44f](https://github.com/dab512/atomic-spec/tree/594a44f0f8c8916faf96a3c13e3247e83b7ae2d3).
