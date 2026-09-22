---
name: avo
description: AVO — AI Video Orchestrator. Agent contract for conversation-driven video production — transcribe, cut, grade, motion, subtitles, verify, deliver. Load for any AVO editing session.
---

# AVO (AI Video Orchestrator)

## Runtime

Resolve once. Do not ask. Consumers: **skills + binary**. MCP and clone only when the user asks.

Never `pip install avo` — PyPI `avo` is Soteria.

Engine zip is **AVO Python only** — not ffmpeg, HyperFrames, watch-skill, CUDA, or model weights. Unused when this AVO repo is the opened folder.

1. **Override** — user said MCP / self-build / clone-python. Honor it. Do not silently use the zip.
2. **Opened folder is an AVO checkout** — `pyproject.toml` name `avo` **and** `src/avo/` **and** `AGENTS.md` contains `<!-- avo:orchestrator:start -->` → `python -m avo.*`. Do **not** use `~/.avo/bin/avo`.
3. **Else** → `~/.avo/bin/avo`. Missing? Run the installer. Do not clone unless asked.

Missing engine: [docs/install/README.md](https://github.com/joaobispo2077/avo/blob/main/docs/install/README.md).

**Slash commands:** `/avo.help`, `/avo.guidelines`, `/avo.pipeline`, `/avo.trim`, `/avo.transcribe`, `/avo.sound`, `/avo.audit`, `/avo.watch`, `/avo.motion`, `/avo.telemetry`, `/avo.learndown`, `/avo.cleanup`, `/avo.stats`, `/avo.models`, `/avo.provider`, `/avo.docs` (also load skill `avo-pipeline`).

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
- Setup: `docs/install/README.md`

## Companion skills

Load **avo-pipeline** when the user invokes any `/avo.*` command or pipeline stage.
Load **avo-provider** when creating or configuring a provider.

## Guided responses

For every AVO-owned response, load and apply the [shared response contract](../avo-pipeline/references/step-status.md),
the shared response contract. Resolve
the current step from durable project state, and end with its exact four-line
workflow footer.
