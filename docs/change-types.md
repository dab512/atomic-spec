English | [Русский](ru/change-types.md)

# Classifying changes

Two independent axes describe a change.

| Field | Values | Question |
|---|---|---|
| `change_class` | compatible, additive, breaking | Does the consumer contract change compatibly? |
| `change_type` (optional) | ParameterChange, RuleChange, FlowChange, ModelChange, BoundaryChange, PlatformChange | What part of the model/process changes? |

Compatible clarifies without behavior change; additive extends without breaking
existing guarantees; breaking changes/removes an existing contract. A parameter
or platform change can be breaking. An optional field does not automatically make
an API change compatible: assess existing consumers and promises.

Preserve rule IDs and never reuse a retired ID for another meaning. Update dates,
return changed contracts to review, record rationale and assess affected parent,
semantic and event links. Use whereused in an explicit scope; absence of references
in a narrow selection does not prove absence of impact.

Create a new atom for an independent responsibility or explicit replacement.
Edit the existing atom for changes within its responsibility, recording history.
Project rules determine reviewers and publication permissions.


[Methodology](methodology.md) · [Gates](gate-validation.md) · [Migration to 2.0](migration-v2.md)
