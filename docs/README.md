# AVO Documentation Index

The documentation for **AVO — AI Video Orchestrator**. Start with the workflow,
then dive into the per-domain systems and delivery specs as needed.

## Documentation voice

Write for the **correct audience by file** — not by mixing tones in one file.

| Audience | Paths | Voice |
| --- | --- | --- |
| Human visitor | [`../README.md`](../README.md), `package.json` / `pyproject.toml` descriptions | Benefit-first UX: short sentences, scannable headings, concrete verbs. No agent checklists. |
| Driving agent | Everything under `docs/`, [`../AGENTS.md`](../AGENTS.md), [`../SKILL.md`](../SKILL.md), [`install/README.md`](install/README.md), `.cursor/rules/`, provider manifests | Dense, precise, checklist-friendly. No marketing fluff. |
| Provider brand | `providers/<name>/` only | Provider-scoped; never repo root. |
| Session logs | External `<footage>/edit/` | Copy from [`templates/logs/`](templates/logs/); do not commit personal entries to the AVO repo. |

**Agent entrypoints:** [`../AGENTS.md`](../AGENTS.md) (canonical rules) →
[`avo-workflow.md`](avo-workflow.md) (pipeline) → domain docs below.

- [`../README.md`](../README.md) — user-facing overview, tool-routing table,
  quickstart, and [use-case prompts](../README.md#use-cases).
- [`../AGENTS.md`](../AGENTS.md) — **canonical** operating rules for every agent
  driving AVO (includes the AVO Orchestrator Operating Rules section).

## Workflow

- [`avo-workflow.md`](avo-workflow.md) — the AVO pipeline in precise, agent-facing
  detail: per-video project model, confidence gate + low-res loop (360p/720p →
  1080p), the watch-skill inspect/fix/verify LOOP, **human approval gates**
  (`edit/preview/`, `edit/review/`), telemetry expectations, hardware advisory,
  post-render learndown + cleanup with the preserved-set invariant, and
  provider-scoped learning.
- [`avo-commands.md`](avo-commands.md) — **`/avo.*` slash commands** (pipeline,
  trim, sound, audit, watch, motion) with shared asset-path schema.
- [`agent-skills.md`](agent-skills.md) — **AVO skills for every agent** (`avo`,
  `avo-pipeline`, `avo-provider`) and non-Cursor prompt equivalents.
- [`templates/project-layout.md`](templates/project-layout.md) — canonical external
  `edit/` layout including `preview/` and `review/`.
- [`templates/review/approval-gate-manifest.md`](templates/review/approval-gate-manifest.md)
  — checklist template agents copy per approval gate.
- [`why-not-editor-mcp.md`](why-not-editor-mcp.md) — decision record: native
  editor MCPs (e.g. CapCut) vs AVO orchestration; for agents, not README copy.
- [`use-cases.md`](use-cases.md) — redirect to [README use cases](../README.md#use-cases) (all prompts in one place).
- [`repo-layout.md`](repo-layout.md) — what ships in git vs install-time vs ignored.
- [`launch.md`](launch.md) — pre-push checklist for GitHub publish.

## Editing & audio

- [`editing-system.md`](editing-system.md) — the YouTube editing workflow,
  philosophy, and common pipeline.
- [`audio-post-production-system.md`](audio-post-production-system.md) — audio
  intake, sync, restoration, and mix-hierarchy system.

## Animation & motion

- [`animation-system.md`](animation-system.md) — the AI-assisted animation and
  motion-design system.
- [`hyperframes-workflow.md`](hyperframes-workflow.md) — HyperFrames, the default
  motion framework, and its CLI loop.
- [`remotion-decision-guide.md`](remotion-decision-guide.md) — when to choose
  Remotion instead of HyperFrames.

## Delivery specifications

- [`delivery-specifications.md`](delivery-specifications.md) — video delivery
  specs and QC.
- [`audio-delivery-specifications.md`](audio-delivery-specifications.md) — audio
  loudness, true-peak, and delivery specs.
- [`animation-delivery-specifications.md`](animation-delivery-specifications.md)
  — animation render and delivery specs.
