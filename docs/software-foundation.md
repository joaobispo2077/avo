# AVO software foundation — project scan

**Task:** `avo-software-foundation` · **Date:** 2026-08-01

This document maps how the repository is organized and which rule layers apply.

---

## What this repo is

**AVO (AI Video Orchestrator)** — local-first agent-driven video pipeline. It **uses**
a bundled Python editing engine (fork lineage from video-use) plus external tools
(watch-skill, HyperFrames). See [engine-vs-orchestrator.md](./engine-vs-orchestrator.md).

---

## Layer model

| Layer | Purpose | Canonical source |
| ----- | ------- | ---------------- |
| **Software foundation** | TDD, SemVer, branches, KISS/DRY, docs | `AGENTS.md` § Software Engineering Foundation + `.cursor/rules/00-core-behavior.mdc` … `50-documentation-policy.mdc` |
| **Editorial / AVO product** | Meaning preservation, format diagnosis, QC gates | `AGENTS.md` body + `.cursor/rules/00-core-editorial-behavior.mdc` … |
| **On-demand skills** | Architecture / pattern diagnosis | `.claude/skills/` and `.cursor/skills/` — `architecture-selection`, `design-pattern-selection` |
| **Pipeline skills** | Video editing workflows | `.claude/skills/` editing skills, `commands/avo/` |

When layers conflict, **editorial meaning and safety rules win** for footage work;
**software foundation wins** for orchestrator code changes unless the user overrides.

---

## Directory map (orchestrator core)

| Path | Role |
| ---- | ---- |
| `src/avo/` | Python engine — transcribe, EDL, grade, render, validation |
| `scripts/` | Cross-platform setup, provider scaffolds, Gate 1/2 runners |
| `tests/` | `pytest` — install, config, engine contracts, gitignore, traces, audio |
| `docs/` | Workflow, launch checklist, versioning, branching, CI |
| `commands/avo/` | Cursor slash commands (`/avo.*`) |
| `agent-skills/` | Skills package for `npx skills add` |
| `providers/` | Schema + `_template/` only in git; personal providers gitignored |
| `bin/install.cjs` | One-command agent install |
| `.github/workflows/` | CI — Gate 1 prerequisites, Gate 2 usability, tests |
| `.specify/` | GitHub Spec Kit marker |

**Not in git (local/dev):** `.cursor/`, `.claude/`, `.agents/`, `specs/` (except backlog), `providers/<real-slug>/`, `tools/*` clones.

---

## Testing stack

- **Runner:** `pytest` (`pip install -e ".[dev]"`) or `npm run test:unit`
- **CI:** `.github/workflows/ci.yml` via `scripts/ci/run-unit-tests.sh`
- **Audit:** [software-quality-audit.md](./software-quality-audit.md)
- **Mindset:** Test Trophy — ~90% cheap unit tests; integration when boundaries crossed; E2E only for critical flows
- **Gate 2:** `src/avo/validate_usability.py`

---

## Versioning (dual)

| Artifact | Scheme | Log |
| -------- | ------ | --- |
| Orchestrator software | SemVer + `v*` tags | `CHANGELOG.md` |
| Video exports | `YYYYMMDD-slug-stage-v001` | `EDITLOG.md` in footage project |

See [versioning.md](./versioning.md).

---

## Agent instruction files

| Tool | Entry |
| ---- | ----- |
| All agents | `AGENTS.md` |
| Claude | `CLAUDE.md` → `@AGENTS.md` |
| Cursor | `.cursor/rules/*.mdc` |
| Copilot | `.github/copilot-instructions.md`, `.github/instructions/*.md` |

---

## Business rules summary

1. Footage and session outputs live **outside** this repo (`<rawDir>/edit/`).
2. Human approval gates before resolution promotion (watch-skill LOOP).
3. Subtitles last in filter chain; word-boundary cuts; verbatim ASR.
4. No git branch orchestration or tag push without explicit user request.
5. Behavior changes only when explicitly requested.
6. Personal provider brands (e.g. `providers/bishop/`) stay local — gitignored.
