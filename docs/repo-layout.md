# AVO repository layout

What belongs **in git** vs **install-time** vs **never in this repo**.

AVO is an **orchestrator**. GitHub ships the contract — scripts, engine package, docs,
manifests, CI, and Spec Kit marker. Heavy tools and skills are installed by
[`install/README.md`](install/README.md) / `scripts/setup.sh`.

---

## In git (orchestrator core)

| Path | Purpose |
| ---- | ------- |
| `README.md`, `LICENSE` | User-facing entry |
| `docs/install/` | Install guide |
| `scripts/install/` | One-command agent install (`install.sh`, `install.ps1`) |
| `bin/install.cjs` | Unified installer implementation |
| `agent-skills/`, `skills.json` | Skills registry package (`npx skills add`) |
| `commands/avo/` | Shipped Cursor slash commands (`/avo.*`) |
| `docs/avo-pipeline/` | Gateway skill + command reference slices |
| `docs/avo-commands.md` | User index for slash commands |
| `AGENTS.md`, `SKILL.md`, `CLAUDE.md` | Agent operating rules |
| `config/` | Orchestrator manifests (`avo.config.json`, `avo.dependencies.json`, model catalog) |
| `schemas/` | Public JSON Schema contracts (`avo.project.schema.json`, `edl.schema.json`) |
| `src/avo/` | Python engine package (transcribe, grade, render, validation) |
| `helpers/` | Temporary import shims → `avo.*` (removed in v0.2.0) |
| `scripts/` | Cross-platform setup (`setup.sh`), agent install (`install/`), CI helpers |
| `docs/` | Workflow, delivery specs, templates, use cases, [engine-vs-orchestrator.md](engine-vs-orchestrator.md), [software-foundation.md](software-foundation.md), [versioning.md](versioning.md), [branching.md](branching.md) |
| `CHANGELOG.md` | Orchestrator SemVer history |
| `tests/` | Unit and contract tests |
| `providers/` | Provider schema + `_template/` scaffold only (personal providers gitignored) |
| `static/avo*`, `static/avo/` | AVO branding (banner, workflow, options SVGs) |
| `.github/` | CI, release, copilot instructions |
| `.specify/` | GitHub Spec Kit marker (or run `specify init` after clone) |
| `package.json`, `package-lock.json` | Node toolchain (HyperFrames CLI, validators) |
| `pyproject.toml`, `uv.lock` | Python engine package |
| `.env.example` | Optional keys template |

---

## Install-time (not in git)

Setup clones or installs these under ignored paths:

| Tool | How | Path / note |
| ---- | --- | ----------- |
| watch-skill | `git clone` | `tools/watch-skill/` |
| ai-memory | `git clone` (`--with-memory`) | `tools/ai-memory/` |
| logo-generator-skill | `git clone` (`--with-logo`) | `tools/logo-generator-skill/` |
| ai-jail | binary / clone (`--with-jail`) | `tools/ai-jail/` or PATH |
| HyperFrames | `npm install` | `node_modules/hyperframes` |
| faster-whisper models | `prepare_transcription.py` | `models/` |
| HyperFrames agent skills | `hyperframes skills update` | user agent dirs, not AVO repo |

See [`../config/avo.dependencies.json`](../config/avo.dependencies.json) and Gate 1:
`scripts/validate-prerequisites.sh`.

---

## Gitignored (local / dev only)

| Path | Why |
| ---- | --- |
| `.agents/`, `.claude/` | Vendored HyperFrames/editing skills (install via HF) |
| `.cursor/`, `.sdd/`, `.cursor-plugin/` | SDD dev framework — not AVO product |
| `.chatgpt/`, `.opencode/`, `.windsurf/`, `.clinerules/` | Alternate agent configs |
| `specs/` | Personal SDD roadmaps and active tasks |
| `models/`, `node_modules/`, `.venv*` | Runtime caches |
| `.avo/`, `.env`, `.ai-memory.toml` | State and secrets |
| `compositions/`, `assets/`, `lib/` | Local HF demos and scratch media |
| `providers/*/` (except `_template/`) | Personal channel/provider brand dirs |
| `tools/watch-skill/` (+ other clones) | External repos |
| `tools/*.py`, `tools/bin/` | Session one-off scripts |
| `skills/` | Legacy optional skills (removed from launch tree) |
| `*egg-info/` | Python build artifacts |

---

## Deleted from launch (legacy video-use)

These were tracked in the old fork and are **removed**:

- `skills/manim-video/`
- `poster.html`
- `static/video-use-banner.png`

---

## Footage projects (always external)

Video work never lives in the AVO repo:

```
<footage>/raw/          # untouched sources
<footage>/edit/         # transcripts, preview, review, masters
```

See [`templates/project-layout.md`](templates/project-layout.md).
