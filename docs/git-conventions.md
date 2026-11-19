English | [Русский](ru/git-conventions.md)

# VCS and review

Follow the project's VCS, branch, commit and review process. Atomic Spec does not
require Git, a branch per role, one PR per gate or automatic publication.
The logical artifact order is **spec → test → feat/fix**; use this commit order
when it helps review. A single task branch may include related business and
architecture atoms, tests and implementation.

Example commit: `fix(PAYMENT-001): prevent a repeated debit`.
Record contract compatibility, affected IDs, gate evidence and scope in the
project's normal review artifact. Confirm required human approval before implementation;
do not ask again for authorization already granted within the current task.

Release tags preserve a reviewed specification snapshot. This repository publishes
versioned source and skill archives. Its GitHub process is an architectural choice
of this distribution, not a mandatory convention for all adopters.


[Methodology](methodology.md) · [Gates](gate-validation.md) · [Migration to 2.0](migration-v2.md)
