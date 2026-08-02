---
name: avo
description: AVO — AI Video Orchestrator. Agent contract for conversation-driven video production — transcribe, cut, grade, motion, subtitles, verify, deliver. Load for any AVO editing session.
---

# AVO (AI Video Orchestrator)

**Install full toolchain:** clone the repo and run `bash install.sh --full --lang en`, or see [install.md](https://github.com/joaobispo2077/avo/blob/main/install.md).

**Slash commands:** `/avo.help`, `/avo.guidelines`, `/avo.pipeline`, `/avo.trim`, `/avo.transcribe`, `/avo.sound`, `/avo.audit`, `/avo.watch`, `/avo.motion`, `/avo.telemetry`, `/avo.learndown`, `/avo.cleanup`, `/avo.stats`, `/avo.provider`, `/avo.docs` (also load skill `avo-pipeline`).

## Session start

1. Declare **provider** (channel/brand) and **where the footage lives** — e.g.
   *The footage is at C:/Videos/my-review* or *this folder*. Create or audit
   providers with skill **`avo-provider`** or `/avo.provider`.
2. All outputs go in `<footage-folder>/edit/` only; never inside the AVO repo.
3. Human approval after watch-skill + transcription analysis before promoting resolution.

## Hard rules (non-negotiable)

1. Subtitles **last** in the filter chain.
2. Per-segment extract + lossless concat; 30ms audio fades at cuts.
3. Never cut inside a word; snap to word boundaries.
4. Word-level verbatim ASR only; cache transcripts per source.
5. Strategy confirmation before execution; human approval at each gate.

## Docs

- Workflow: `docs/avo-workflow.md` in the AVO repo
- Commands: `docs/avo-commands.md`
- Skills (all agents): `docs/agent-skills.md`
- Use cases: `agent-skills/avo/references/use-cases.md`
- Setup: `install.md`

## Companion skills

Load **avo-pipeline** when the user invokes any `/avo.*` command or pipeline stage.
Load **avo-provider** when creating or configuring a provider.
