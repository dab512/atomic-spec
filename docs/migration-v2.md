English | [Русский](ru/migration-v2.md)

# Migrating to 2.0

This is a breaking methodology release. The previous snapshot remains available
at [594a44f](https://github.com/dab512/atomic-spec/tree/594a44f0f8c8916faf96a3c13e3247e83b7ae2d3).
Existing projects migrate deliberately; installing the skill does not authorize
rewriting an application's specifications or bypassing its process.

| Previous convention | 2.0 |
|---|---|
| Analyst → Developer → Tester, gates A/B/C | Analysis A → scenarios B → tests C/RED → implementation D/GREEN → acceptance |
| Tech Spec inside each feature | Standalone architecture domain; implementation notes near code |
| Optional test plan before/alongside code | Executable behavioral tests before new/changed behavior |
| Unidentified Gherkin scenarios | Stable AC headings outside fences, explicit registry |
| Three status axes and folder-derived active | One lifecycle; scoped acceptance evidence separately |
| Mandatory spec/feat/test branches | Project VCS; artifact order spec → test → feat/fix |
| Full tree reading | Explicit related atoms and permitted bounded search |

Preserve IDs and all normative rules during extraction. Keep the meaning of an ID;
record changed contracts and compatibility, do not silently recycle identifiers.
Split DMT by meaning. Do not copy debugging notes into architecture requirements.
Legacy `active` becomes `ready` unless scoped acceptance supports `implemented`.
Preserve old implementation/verification data as historical evidence with its
actual scope/revision; never assume that it establishes new stack readiness.

The bundled Guard is now the pinned Git distribution. Git check modes use exact
SHA; an existing Arc project keeps its configured Arc-aware Guard. Python minimum
for the bundle is 3.11. APM/plugin metadata is version 2.0.1. The standalone Guard
has an independent version/revision; it is not renamed to methodology 2.0.1.


[Methodology](methodology.md) · [Gates](gate-validation.md) · [Migration to 2.0](migration-v2.md)
