English | [Русский](ru/gate-validation.md)

# Gates and acceptance

| Gate | Required evidence |
|---|---|
| A — analysis | Actors, outcomes, verifiable rules, model/guarantees, compatibility/impact, closed blocking questions; business contract complete without old code |
| B — scenarios | Every affected rule/guarantee has an AC or explicit verification method; concrete outcomes, applicable failures/boundaries/permissions/retries; architectural contracts sufficient for tests |
| C — RED | Executable tests run before behavior implementation; command, test and expected requirement failure recorded; annotations already valid |
| D — GREEN | Same tests and affected regressions pass; code complies with both requirement domains; no weakened assertions or invented rules |

Before implementation, obtain human specification approval when the project requires
it. Existing authorization within scope remains valid. Formal validation is not approval.

Import errors, missing databases, skip/xfail, no tests and unstarted jobs are not
RED or PASS. A minimal interface skeleton can enable test execution without adding
business behavior. For an existing correct behavior retain baseline GREEN.
For a bug reproduce RED on old code or an isolated controlled mutation; never damage
shared code or environments for the demonstration.

## Acceptance after Gate D

Record `requirement → AC → automated test → result`, scope/revision, commands,
RED/GREEN facts and remaining scenarios. Run project-required checks and local-dev
journeys. Review `comments` against requirements and real code, then rerun Guard
if inputs changed. Every discovered defect receives its own regression.

A complete Guard report only establishes formal validity within its selected scope.
It does not establish business correctness, actual test success, deployment or every
architecture's readiness. Preserve a failed/unrun result explicitly.


[Methodology](methodology.md) · [Gates](gate-validation.md) · [Migration to 2.0](migration-v2.md)
