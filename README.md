**English** | [Русский](README.ru.md)

<p align="center">
  <img src="assets/logo.svg" alt="Atomic Spec" width="480"/>
</p>

<p align="center">
  <strong>An AI-native methodology for living requirements — one atom, one file, one unit of knowledge.</strong>
</p>

Atomic Spec is an **AI-native** methodology that unifies **Domain-Driven Design**, **Test-Driven Development**, **Use-Case-Driven**, and **Requirements-Driven** approaches into a single flow orchestrated by AI agents. Every requirement is a living artifact with history, not a frozen document.

## Core Idea

Every requirement lives in a single `*.spec.md` file (an "atom") that progresses through three **AI agent roles**:

**Analyst Agent** (business intent) → **Developer Agent** (implementation) → **Tester Agent** (verification)

An **Orchestrator Agent** coordinates the pipeline, switches roles, and validates artifacts at each **Gate** checkpoint. The entire workflow — from decomposition to code to tests — is driven by AI agents following strict contracts.

## Key Principles

- **AI-native**: three specialized AI agents (Analyst, Developer, Tester) orchestrated by a meta-agent
- **One atom = one file = one unit of knowledge** (`*.spec.md`)
- **Progressive disclosure**: from business intent to test cases and code
- **Technology agnostic core**: the heart of an atom is platform-independent
- **Traceability**: every artifact references its source atom
- **Contract-based agent pipeline**: each agent role produces artifacts, validated at gates

## Atom Hierarchy

```
System                          <- changes once in a product's lifetime
 └── Domain (Bounded Context)   <- changes on strategic shifts
      └── Use Case              <- changes almost every sprint
           └── Scenario (leaf)  <- atomic test case
```

## Quick Start

1. Copy `templates/atom-template.spec.md` to your project's `specs/` directory
2. Fill in the Analyst sections (Intent, Domain Rules, AC, DMT, Constraints)
3. Pass Gate A validation
4. Fill in Developer sections (Tech Spec, Platform API, Implementation Notes)
5. Pass Gate B validation
6. Fill in Tester sections (Test Plan, Platform Tests, Coverage Matrix)
7. Pass Gate C validation

See [Getting Started](docs/getting-started.md) for a detailed walkthrough.

## AI Agent Orchestrator

Atomic Spec is designed to be executed by AI agents. The included **Orchestrator Skill** for [Claude Code](https://claude.ai/claude-code) drives the full pipeline:

1. **Decomposes** a task into atoms (spec files)
2. **Switches** between Analyst → Developer → Tester agent roles
3. **Validates** artifacts at each Gate before passing to the next role
4. **Follows** git conventions for branches, commits, and PRs

Install the skill and your AI agent becomes a full Atomic Spec practitioner. See [`skill/`](skill/) directory and [installation instructions](skill/README.md).

```
You: "Design a user registration feature"

Orchestrator: Decomposes → domain AUTH, type additive
  [ROLE: Analyst]    → Intent, Domain Rules, AC, Constraints → Gate A ✅
  [ROLE: Developer]  → Tech Spec, API, Code                 → Gate B ✅
  [ROLE: Tester]     → Test Plan, Coverage Matrix, Tests     → Gate C ✅
Done: spec + code + tests, all traced to atoms.
```

## Documentation

| Document | Description |
|----------|-------------|
| [Getting Started](docs/getting-started.md) | Step-by-step guide to your first atom |
| [Methodology](docs/methodology.md) | Full methodology reference |
| [Atom Anatomy](docs/atom-anatomy.md) | Structure of a spec file |
| [Roles & Pipeline](docs/roles-and-pipeline.md) | Analyst, Developer, Tester roles |
| [Gate Validation](docs/gate-validation.md) | Gate A, B, C checklists |
| [Git Conventions](docs/git-conventions.md) | Branching, commits, PRs |
| [Change Types](docs/change-types.md) | Parameter, Rule, Flow, Model, Boundary changes |
| [Amendments](docs/amendments.md) | How to handle in-flight changes |

## Agent Role References

Detailed guides for each AI agent role:

- [Analyst Agent](skill/references/analyst.md) — Intent, Domain Rules, AC, Constraints
- [Developer Agent](skill/references/developer.md) — Tech Spec, API, Code, Implementation Notes
- [Tester Agent](skill/references/tester.md) — Test Plan, Coverage Matrix, Platform Tests

## Meta-Specification

This repository eats its own dog food — the methodology itself is described using Atomic Spec format in the [`specs/`](specs/) directory. See [`specs/system.spec.md`](specs/system.spec.md) as the entry point.

## File Structure

```
atomic-spec/
├── README.md
├── README.ru.md
├── LICENSE
├── docs/                        # Classic documentation
│   ├── getting-started.md
│   ├── methodology.md
│   ├── atom-anatomy.md
│   ├── roles-and-pipeline.md
│   ├── gate-validation.md
│   ├── git-conventions.md
│   ├── change-types.md
│   └── amendments.md
├── skill/                       # AI agent skill (Claude Code)
│   ├── SKILL.md                 # Orchestrator prompt
│   ├── references/              # Role reference guides
│   │   ├── analyst.md
│   │   ├── developer.md
│   │   └── tester.md
│   └── assets/
│       └── atom-template.spec.md
├── specs/                       # Meta: Atomic Spec describes itself
│   ├── system.spec.md
│   └── methodology/
│       ├── domain.spec.md
│       ├── _index.md
│       ├── atom-lifecycle/
│       ├── role-pipeline/
│       └── gate-validation/
├── templates/                   # Atom template for your projects
│   └── atom-template.spec.md
└── website/                     # Landing pages (HTML)
    ├── index.html
    └── orchestrator.html
```

## Website

Browse the interactive documentation: **[dab512.github.io/atomic-spec](https://dab512.github.io/atomic-spec/)**

## The Methodology Test

> Can you reconstruct the complete domain history — who, when, why made each decision — only from `git log` on `*.spec.md` files? **Yes** → methodology applied correctly.

## License

MIT License — see [LICENSE](LICENSE).
