---
applyTo: "**"
---

# Design Principles Instructions

Follow `AGENTS.md` and `.cursor/rules/30-design-principles.mdc`.

## Core principles

- **KISS** — simplest correct solution
- **DRY** — single source of truth for knowledge, not mere code similarity
- **YAGNI** — no hypothetical features or abstractions
- **SOLID** — when boundaries earn it; skip ceremony in small scripts
- **Cohesion / coupling** — related code together; minimize cross-module leaks
- **Functional clarity (JS/TS)** — pure functions, explicit data flow when it aids tests

## Design patterns

- **Not default.** Load skill `design-pattern-selection` before applying Strategy,
  Observer, Facade, Decorator, Adapter, or Singleton.
- **Singleton:** avoid unless strongly justified (hurts testing).

## Architecture

- Load skill `architecture-selection` before new layer folders or DDD structure.
- AVO today: pragmatic `helpers/` + `scripts/` — Hexagonal at IO edges only.

## Preserve behavior

Refactors only when necessary for the requested change or when explicitly asked.
