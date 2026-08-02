# Deep animation direction exemplar

**Status:** reference · **Roadmap:** [`specs/todo-roadmap/avo-pipeline-demo-motion/`](../todo-roadmap/avo-pipeline-demo-motion/roadmap.md)

This doc explains how AVO should receive, structure, and execute **deep animation
direction** — the kind of brief creators give when they want timed liquid-glass
cards, karaoke typography, pipeline storytelling, and sync-to-the-second motion.

## Why this exists

Most README use cases show **what** to ask for in one paragraph. Creators doing
serious motion work need **beat-level direction**: layout zones, trigger phrases,
density levels, motion tokens, and acceptance tests. Without that structure, agents
improvise and sync drifts.

This exemplar adapts the **phased DAG** from
[maxframe `release.yml`](https://github.com/joaobispo2077/maxframe/blob/main/.github/workflows/release.yml)
to AVO motion:

```
Phase 0  determine-version     →  transcribe + extract beats (skip if none)
Phase 1  build-windows (×N)    →  parallel HyperFrames slot builds
Phase 2  smoke-windows (×N)    →  parallel 720p proof + watch-skill LOOP
Phase 3  release               →  composite QC → human gate → promote → deliver
```

## Use case

**Live pipeline demo with deep animation direction** — a talking-head recording where the
creator explains AVO's edit-and-motion workflow live. Full prompt in
[README § Live pipeline demo](../README.md#live-pipeline-demo-four-beat-liquid-glass-cards-synced-to-the-second).

## Canonical spec

The full beat map lives at:

**[`specs/active/avo-pipeline-demo-motion/animation-direction.md`](../active/avo-pipeline-demo-motion/animation-direction.md)**

Four beats:

| Beat | Trigger | Visual |
| --- | --- | --- |
| A | "…editing live together" | Left liquid glass + karaoke title pop-in |
| B | "…mistakes…okay" | Bottom "Mistakes will be cut." + right trim viz |
| C | pipeline / raw file | Center card pipeline story (5 sub-beats) |
| D | "HyperFrames instead" | Left + right alt-palette cards |

## How agents should use it

1. **Intake** — Run animation diagnosis (format, density, framework). HyperFrames default.
2. **Anchor** — Transcribe; map trigger phrases to word timestamps (±100 ms tolerance).
3. **Spec** — Copy the beat-map structure from `animation-direction.md` for new projects.
4. **Design** — Fill `edit/DESIGN.md` from `docs/templates/animation-design-system.md`.
5. **Storyboard** — One row per beat → one `slot_*` folder.
6. **Build parallel** — Spawn sub-agents per slot (AVO motion hard rule 10).
7. **Proof parallel** — 720p + watch-skill LOOP per slot before composite.
8. **Gate** — Human approval in `edit/review/motion-proof/approval-gate.md`.
9. **Release** — Promote to source resolution; deliver manifest.

## Session entry

```text
/avo.pipeline
Provider: tech-first-look
The footage is at <rawDir>
Follow specs/active/avo-pipeline-demo-motion/animation-direction.md
Motion: talking-head-recut + general-video (Beat C)
Prove at 720p until I approve each gate.
```

## Related

- [`docs/animation-system.md`](animation-system.md) — workflow and review gates
- [`docs/avo-pipeline/references/motion.md`](avo-pipeline/references/motion.md) — slot layout
- [`docs/templates/animation-design-system.md`](templates/animation-design-system.md) — DESIGN.md template
- [`agent-skills/avo/references/use-cases.md`](../agent-skills/avo/references/use-cases.md) — skill map

## Execute the roadmap

```bash
/execute-parallel avo-pipeline-demo-motion
/execute-task task-005    # formalize spec
/execute-task task-010    # first parallel slot
```
