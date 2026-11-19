# Atomic Spec

Read skills/atomic-spec-orchestrator/SKILL.md and related atoms in specs/registry.json.
Business requirements describe the methodology; publication and tool decisions
belong to specs/architecture. Preserve IDs and record breaking changes.

Use the bundled Guard and explicit scope for this repository. Do not operate
on the user's installed skill. Do not execute setup on a different project.

Validation: python3 tools/release.py check (dependencies in requirements-dev.txt).
Build reviewable release assets: python3 tools/release.py build.
Never claim skipped tests or an unstarted remote CI as PASS.
Do not add tool attribution to commits. Publishing requires user authorization.
