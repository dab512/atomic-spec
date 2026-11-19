English | [Русский](ru/atom-anatomy.md)

# Atom anatomy

The business template is [templates/atom-template.spec.md](../templates/atom-template.spec.md).
The architecture template is [templates/architecture-template.spec.md](../templates/architecture-template.spec.md).

Metadata includes stable `id`, `type`, `parent`, `title`, `status`, `change_class`,
optional `change_type`, actors/events, owners and dates. Supported hierarchy:
system → domain → aggregate/use-case → scenario. Use the existing project levels;
empty intermediate atoms are unnecessary. Paths and naming belong to the project.

## Business atom

Intent; Domain Rules; Acceptance Criteria; Business Model; Constraints;
Open Questions; Decision Log. Business concepts, events and invariants stay here.
Measurable mandatory guarantees receive stable DR/BR IDs for direct tracing.
Decision tables are useful when combinations matter; they are not mandatory filler.

Declare each rule outside a code fence. Declare AC as a heading followed by Gherkin:

```markdown
### AC-1. Repeated payment

Verifies DR-1.

~~~gherkin
Scenario: No second debit
  Given a payment has completed
  When the same payment is retried
  Then the total debit remains unchanged
~~~
```

## Architecture atom

Intent; Requirements Served; Domain Rules; Acceptance Criteria; Contracts;
Alternatives and Replacement; Open Questions; Decision Log. It may name APIs,
schemas, transactions and selected technologies. `satisfies` and Requirements Served
express business links whose meaning is reviewed manually; Guard does not validate
that frontmatter graph automatically.

Test code, coverage/run reports and implementation file maps live with the selected
implementation. The business atom remains usable for a different stack.


[Methodology](methodology.md) · [Gates](gate-validation.md) · [Migration to 2.0](migration-v2.md)
