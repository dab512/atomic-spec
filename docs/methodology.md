English | [Русский](ru/methodology.md)

# Methodology 2.0

Atomic Spec combines Domain-Driven, Use-Case-Driven, Requirements-Driven development
with executable tests before implementation. One atom is one `*.spec.md` file with
a stable ID, rules and observable acceptance criteria.

The specification must be sufficient to reproduce the business functionality
without reading the old code. VCS history preserves why decisions were made;
it is an audit trail, not a substitute for a complete current contract.

## Business and architecture

Business domains describe actors, outcomes, rules, invariants and guarantees.
The separate `architecture/` domain records selected technologies, component
boundaries and contracts, alternatives and replacement conditions. It belongs
to the same specification tree. A feature does not require its own technical duplicate.
Implementation file maps, debugging history and run reports live near the code.

A technical product may have an API or protocol as its external business contract.
Separate consumer guarantees from replaceable mechanisms by meaning.

## Workflow

Context → analysis / Gate A → Gherkin / Gate B → executable tests / Gate C (RED)
→ implementation / Gate D (GREEN) → acceptance.

Roles are responsibilities that one agent or person can assume. Delegation is
optional. Each role reads all necessary requirements and changes its own artifacts.
Project instructions determine VCS, review, approvals, tooling and test scope.

## Status

`draft → review → ready → implemented → deprecated` is the canonical atom lifecycle.
`ready` means the contract has passed Gate B; it does not claim working code.
`implemented` requires accepted behavior in a declared implementation scope/revision.
It does not mean deployment or implementation on every stack. An amended contract
returns to `review`. A regression invalidates the corresponding acceptance claim.

Optional implementation/verification records hold scoped evidence, not an alternative
atom lifecycle. Folder location does not set status. Read selected atoms through
an explicit registry; a repository-wide scan is not a prerequisite.


[Methodology](methodology.md) · [Gates](gate-validation.md) · [Migration to 2.0](migration-v2.md)
