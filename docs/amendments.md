English | [Русский](ru/amendments.md)

# Amendments

Classify compatibility and change type, pin the previous revision, record the
reason and affected IDs. Preserve established IDs; add new IDs for new obligations.
Retiring a rule preserves its history and replacement, without recycling its ID.

Return the changed contract to review. Update the applicable business and architecture
atoms, scenarios, existing code annotations and tests together. Rerun affected gates:
changed behavior starts at analysis/Gherkin; a defective implementation gets a
reproducing test before its fix. Approval follows project rules.

A separate amendment atom is optional when it helps record a substantial change;
it is not required for every edit. For a genuinely independent replacement,
register a new atom with `supersedes` and mark the old one deprecated.

Do not rewrite requirements to make a chosen algorithm pass. If a test was wrong,
correct it against the original requirement, record why and repeat RED/GREEN.


[Methodology](methodology.md) · [Gates](gate-validation.md) · [Migration to 2.0](migration-v2.md)
