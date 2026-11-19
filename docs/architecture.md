English | [Русский](ru/architecture.md)

# Architecture and portability

An architecture atom describes an independently useful decision or restriction,
possibly shared by several business domains. It states the guarantees served,
applicability, selected contracts, alternatives, trade-offs and replacement conditions.
Keep business guarantees in business atoms and replaceable mechanisms in architecture.
A protocol can be the business subject of a technical product.

## Move to another stack

1. Pin the business atoms, IDs, rules and AC to a revision.
2. Check their completeness without relying on old code. Record missing decisions
   as questions, not assumptions silently promoted to requirements.
3. Replace architecture for the target stack. Preserve previous variants in history
   or separate spec-roots; one registry must not contain competing versions of an ID.
4. Write new executable tests against the architectural contracts and prove RED.
5. Implement GREEN and accept the same business outcomes in the new scope.

A changed business guarantee is a separately classified contract change.
When migrating mixed atoms, move normative technical decisions out of Tech Spec;
keep debugging history and file maps with the implementation. Split Domain Model
Touch by meaning and verify that no rule or reference was lost.


[Methodology](methodology.md) · [Gates](gate-validation.md) · [Migration to 2.0](migration-v2.md)
