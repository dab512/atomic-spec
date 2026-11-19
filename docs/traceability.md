English | [Русский](ru/traceability.md)

# Traceability and Spec Guard

Declare and register a requirement before referencing it. Add real comment
annotations while writing each required code block and independent test scenario.
Keep the URI and a meaningful explanation in the same continuous comment group.
Docstrings and string literals are not annotations. Respect the project profile
for language, coverage, helpers and fixtures; do not annotate every line.

```python
# atomic-spec://PAYMENT-001/DR-1
# Retrying the same payment never increases the total debit.
# atomic-spec://ARCH-STORAGE-001/DR-1
# Persist the result and replay identity atomically.
def apply_payment():
    ...
```

The IDs above illustrate syntax; use existing requirements of your project.
Update existing links and explanations when changing the requirements they claim.
Never invent IDs to satisfy the checker or postpone annotations until final review.

## Select the tool

Use the project's configured Guard and normal commands. A broken/missing dependency
is not permission to run a second bundled instance. If no Guard is configured,
the skill provides pinned source from [Atomic Spec Guard](https://github.com/dab512/atomic-spec-guard).
Full instructions: skills/atomic-spec-orchestrator/references/specguard.md.

`getcontext brief/full`: code to requirements/documents. `whereused`: requirement
to references in the chosen scope. `comments`: explanations for semantic review.
`audit`: complete selected files. Git `check`: explicit base/revision or working tree.
Read the report and preserve complete/scope/revision/exclusions; zero errors do
not establish semantic correctness or a complete project index.

The frontmatter graph `satisfies` requires human/agent semantic review; this
release's Guard does not automatically validate that graph.


[Methodology](methodology.md) · [Gates](gate-validation.md) · [Migration to 2.0](migration-v2.md)
