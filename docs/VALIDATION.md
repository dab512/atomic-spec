# Release 2.0.2 acceptance

Local environment: Python 3.13.5, Playwright 1.55.0 with installed Chrome,
PyYAML 6.0.3, Ruff 0.15.15, Node 24.4.1 and Go 1.24.5. Existing local development
dependencies were reused; runtime code is exercised from the extracted skill.

- The old business template reproduced SPEC004 for a real AC-1 reference.
  The same test passes with the new template's AC heading outside the fence.
- Eight integration checks pass, without skips: template resolution; extracted
  Python/JSON launcher commands and invalid-reference mutation; prepared Go/TS/YAML
  adapters; deterministic source/skill archives and SHA256SUMS; rejection of
  corrupted vendored source and broken local links; real page interaction and
  geometry at 375×812 and 1440×900 across EN/RU and the orchestrator route.
- Ruff check/format and skill-creator quick_validate pass.
- The repository's project Guard audits tools/release.py and tests/test_release.py:
  complete=true, zero errors/warnings/notices. Normative URI targets resolve.
- Vendored Guard is adapted from the pinned Git revision
  34c096ef1ac8cebdc042647572f111ffcda9fa72; the adapted source file set and SHA-256 are checked.
- The archive is a verified installation channel. Live installation through APM
  was not run; metadata/layout compatibility is retained.

Scope: distribution behavior, documentation routes, packaging and formal traceability.
These checks do not prove that every user project follows the methodology or that
all `satisfies` relationships are semantically correct. That requires scoped review.
Remote GitHub Actions and Pages results are recorded by their corresponding runs;
local acceptance is not presented as a remote CI result.

## Neutral distribution follow-up

The current file tree and both build artifacts are checked by distribution-policy.json.
The initial naming regression failed on the preceding source tree, then passed after
normalization. Controlled content/path mutations continue to be rejected.
All 210 adapted checker regressions pass, including the real language parsers;
its self-check reports zero errors with advisory diagnostics retained.
The enclosing project checks pass eight integration scenarios without skips.
The adaptation changes requirement namespaces, example labels and fixture names;
ORIGIN.json records these changes instead of claiming byte identity with the base snapshot.
