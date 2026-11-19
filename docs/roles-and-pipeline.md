English | [Русский](ru/roles-and-pipeline.md)

# Roles and pipeline

| Responsibility | Reads | Produces | Checkpoint |
|---|---|---|---|
| Analyst | Goal, existing business and architecture atoms | Rules, model, guarantees, impact, decisions | A |
| Tester: scenarios | Rules and applicable architecture | Stable AC with observable Gherkin outcomes | B |
| Tester: automation | AC and agreed technical contracts | Executable behavioral tests and RED evidence | C |
| Developer | Both requirement domains, AC, tests, RED cause | Implementation, simultaneous annotations, GREEN | D |
| Tester: acceptance | Requirements, real code, all results | Coverage/evidence matrix and scoped conclusion | Acceptance |

Read every requirement needed for the task, regardless of which role authored it.
Change only your responsibility's artifacts. An inconsistent requirement returns
to analysis; an incorrect test is corrected against the original requirement and
its reason is recorded. Changing behavior returns to analysis and Gherkin.

Declare `[ROLE: Analyst]`, `[ROLE: Tester]`, `[ROLE: Developer]` when switching.
A single agent can perform all roles. There is no mandatory subagent or branch per role.
A role switch or a green Guard report does not authorize publication or deployment.


[Methodology](methodology.md) · [Gates](gate-validation.md) · [Migration to 2.0](migration-v2.md)
