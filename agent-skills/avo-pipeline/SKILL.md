---
name: avo-pipeline
description: Gateway for AVO slash commands (/avo.help, /avo.organize, /avo.direction, /avo.briefstart, /avo.guidelines, /avo.pipeline, /avo.trim, /avo.transcribe, /avo.sound, /avo.sync, /avo.audit, /avo.watch, /avo.motion, /avo.captions, /avo.talking-head, /avo.rights, /avo.audio-qc, /avo.color, /avo.grade, /avo.format, /avo.framework, /avo.chapters, /avo.thumbnail, /avo.end-screen, /avo.deliver, /avo.shorts, /avo.reframe, /avo.podcast-clip, /avo.trailer, /avo.pr-video, /avo.changelog-video, /avo.explainer, /avo.slideshow, /avo.launch, /avo.music-video, /avo.beat-edit, /avo.figma, /avo.media, /avo.motion-graphics, /avo.general, /avo.remotion-port, /avo.screencast, /avo.retention, /avo.animation-qc, /avo.telemetry, /avo.learndown, /avo.cleanup, /avo.update, /avo.stats, /avo.costs, /avo.metrics, /avo.models, /avo.docs). Load when the user invokes any /avo.* command or declares Footage/rawDir asset paths.
---

# AVO pipeline commands (gateway)

Entry skill for **`/avo.*`** slash commands. Hard rules: this skill’s Non-negotiable section and skill `avo`. Workflow: [docs/avo-workflow.md](https://github.com/joaobispo2077/avo/blob/main/docs/avo-workflow.md). No repo-relative root `SKILL.md`.

## Runtime

Resolve once. Do not ask. Consumers: **skills + binary**. MCP and clone only when the user asks.

Never `pip install avo` — PyPI `avo` is Soteria.

Engine zip contains **AVO Python and the bundled Playwright driver (including Node)** — not ffmpeg, HyperFrames, watch-skill, CUDA, or model weights. Unused when this AVO repo is the opened folder.

1. **Override** — user said MCP / self-build / clone-python. Honor it. Do not silently use the zip.
2. **Opened folder is an AVO checkout** — `pyproject.toml` name `avo` **and** `src/avo/` **and** `AGENTS.md` contains `<!-- avo:orchestrator:start -->` → `python -m avo.*`. Do **not** use `~/.avo/bin/avo`.
3. **Else** → `~/.avo/bin/avo`. Missing? Run the installer. Do not clone unless asked.

## Invocation cost context

Read [cost guidance](references/costs.md) when starting/resuming a video or changing its driving agent. Pass an explicit metadata-only descriptor through `--cost-context <JSON>` on session start/pipeline run when the caller can supply it. Reuse its operation ID only for the same retry. Missing context remains an unknown expected host; do not borrow the previous agent, infer human/CI execution, or derive a session from an MCP transport ID.

Context registration alone does not read source files, qualify a collector or measure a host conversation. Automatic collection requires the accepted context's explicit source attachment and exact-version qualified profile. Report collection diagnostics while continuing authorized editing. A model or agent switch preserves earlier evidence and the video's accounting identity.

Use the runtime resolved for the requested workflow. With skills only and no engine/checkout/MCP runtime, explain that descriptors can be prepared but no ledger mutation or collection has executed. Do not install vendor SDKs, activate hooks/OTel, poll accounts or clone/install AVO solely to manufacture accounting. Normal runtime setup for a requested editing workflow remains governed by the Runtime section.

## Motion engine selection before workflow loading

This section applies to motion-authoring workflows. `/avo.organize` routes directly to its library reference without selecting or provisioning a motion engine.

Parse the current direct user instruction using the shared arguments before any engine-specific workflow. Run `avo cli animation engine-show --json`, adding the exact `--project`/`--provider` context and canonical `--motion-engine` override when supplied. Checkout equivalent: `python -m avo.cli animation engine-show`. Global inspection/preferences and runtime setup need no footage project.

HyperFrames remains the built-in default. Direct "no frameworks", "without a framework", "framework-free", or unqualified "avoid HyperFrames" means invocation `code-drawn`; a compatible named Remotion alternative remains explicit Remotion and must disclose its unavailable AVO adapter. Preserve skip-motion. Quoted material, questions, and negated exclusions have no execution authority. Resolve contradictory explicit choices once before source mutations.

For code-drawn, load the portable [advanced code-drawn guide](references/code-drawn.md) and relevant topic sections before the router below. Do not load or initialize HyperFrames as a prerequisite. The advanced label explains author-owned seeking, assets, dependencies and QC; selection itself adds no human approval gate. Keep current run selection and recorded animation separate from future defaults.

## Command router

| User invokes | Read |
| ------------ | ---- |
| /avo.costs or /avo.metrics | [references/costs.md](references/costs.md) |
| `/avo.help` (alias `/avo --help`) | [`references/help.md`](references/help.md) |
| `/avo.organize` | [`references/organize.md`](references/organize.md) |
| `/avo.guidelines --youtube` | [`references/guidelines-youtube.md`](references/guidelines-youtube.md) |
| `/avo.guidelines --eq` | [`references/guidelines-eq.md`](references/guidelines-eq.md) |
| `/avo.guidelines --breathing` | [`references/guidelines-breathing.md`](references/guidelines-breathing.md) |
| `/avo.guidelines --tiktok` | [`references/guidelines-tiktok.md`](references/guidelines-tiktok.md) |
| `/avo.guidelines --shorts` | [`references/guidelines-shorts.md`](references/guidelines-shorts.md) |
| `/avo.guidelines` (no flag) | [`references/guidelines.md`](references/guidelines.md) |
| `/avo.docs` | [`references/docs.md`](references/docs.md) |
| `/avo.direction` | [`references/direction.md`](references/direction.md) |
| `/avo.briefstart` | [`references/briefstart.md`](references/briefstart.md) |
| `/avo.pipeline` | [`references/pipeline.md`](references/pipeline.md) |
| `/avo.trim` | [`references/trim.md`](references/trim.md) |
| `/avo.transcribe` | [`references/transcribe.md`](references/transcribe.md) |
| `/avo.sound` (mix/NR) | [`references/sound.md`](references/sound.md) |
| `/avo.sound create` | [`references/sound-create.md`](references/sound-create.md) |
| `/avo.sync` | [`references/sync.md`](references/sync.md) |
| `/avo.audit` | [`references/audit.md`](references/audit.md) |
| `/avo.watch` | [`references/watch.md`](references/watch.md) |
| `/avo.motion` | [`references/motion.md`](references/motion.md) |
| `/avo.captions` | [`references/captions.md`](references/captions.md) |
| `/avo.talking-head` | [`references/talking-head.md`](references/talking-head.md) |
| `/avo.rights` | [`references/rights.md`](references/rights.md) |
| `/avo.audio-qc` | [`references/audio-qc.md`](references/audio-qc.md) |
| `/avo.color` | [`references/color.md`](references/color.md) |
| `/avo.chapters` | [`references/chapters.md`](references/chapters.md) |
| `/avo.thumbnail` | [`references/thumbnail.md`](references/thumbnail.md) |
| `/avo.end-screen` | [`references/end-screen.md`](references/end-screen.md) |
| `/avo.deliver` | [`references/deliver.md`](references/deliver.md) |
| `/avo.shorts` | [`references/shorts.md`](references/shorts.md) |
| `/avo.reframe` | [`references/reframe.md`](references/reframe.md) |
| `/avo.podcast-clip` | [`references/podcast-clip.md`](references/podcast-clip.md) |
| `/avo.trailer` | [`references/trailer.md`](references/trailer.md) |
| `/avo.pr-video` | [`references/pr-video.md`](references/pr-video.md) |
| `/avo.changelog-video` | [`references/changelog-video.md`](references/changelog-video.md) |
| `/avo.explainer` | [`references/explainer.md`](references/explainer.md) |
| `/avo.slideshow` | [`references/slideshow.md`](references/slideshow.md) |
| `/avo.launch` | [`references/launch.md`](references/launch.md) |
| `/avo.music-video` | [`references/music-video.md`](references/music-video.md) |
| `/avo.beat-edit` | [`references/beat-edit.md`](references/beat-edit.md) |
| `/avo.figma` | [`references/figma.md`](references/figma.md) |
| `/avo.media` | [`references/media.md`](references/media.md) |
| `/avo.motion-graphics` | [`references/motion-graphics.md`](references/motion-graphics.md) |
| `/avo.general` | [`references/general.md`](references/general.md) |
| `/avo.remotion-port` | [`references/remotion-port.md`](references/remotion-port.md) |
| `/avo.screencast` | [`references/screencast.md`](references/screencast.md) |
| `/avo.format` | [`references/format.md`](references/format.md) |
| `/avo.framework` | [`references/framework.md`](references/framework.md) |
| `/avo.grade` | [`references/grade.md`](references/grade.md) |
| `/avo.retention` | [`references/retention.md`](references/retention.md) |
| `/avo.animation-qc` | [`references/animation-qc.md`](references/animation-qc.md) |
| `/avo.telemetry` | [`references/telemetry.md`](references/telemetry.md) |
| `/avo.learndown` | [`references/learndown.md`](references/learndown.md) |
| `/avo.cleanup` | [`references/cleanup.md`](references/cleanup.md) |
| `/avo.update` | [`references/update.md`](references/update.md) |
| `/avo.stats` | [`references/stats.md`](references/stats.md) |
| `/avo.models` | [`references/models.md`](references/models.md) |
| `/avo.provider` | [`references/provider.md`](references/provider.md) — load skill **`avo-provider`** |

Always parse shared args first: [`references/arguments.md`](references/arguments.md). Full map: [`references/command-map.md`](references/command-map.md).

## Guided responses

For every routed command, load and apply the [shared response contract](references/step-status.md).
Read the wrapper's
workflow guidance and the routed reference's step/state mapping, resolve state
from the declared durable artifact, and end every progress, input, blocker, and
completion response with exactly one four-line footer.

## Non-negotiable

1. Declare `provider` + `rawDir` before footage stages. Standalone code-drawn uses an explicit external ProjectDir; global preference/runtime operations require no footage context.
2. **Video-candidate pre-human gate:** exact-candidate Watch + transcript analysis +
   canonical lineage/projection/QC before each human approval gate (see [`references/cuts.md`](references/cuts.md),
   [`references/watch.md`](references/watch.md), workflow §4b).
   Library move/transcription approvals instead bind the exact prepared source packet under `references/organize.md`; they do not select an edit or confer video-candidate approval.
3. Subtitles last in filter chain; 30ms audio fades at cuts.
4. Session outputs only under `<rawDir>/edit/`.

## Install (Cursor)

Copy shipped commands into your project or user config:

```bash
# from AVO repo root
cp -r commands/avo .cursor/commands/
```

Or install per [`docs/avo-commands.md`](../../docs/avo-commands.md).

## Canonical timeline gateway

Every editing command resolves the same video/provider context and declares its integration mode. CMap is raw-only. BMap is based only on the latest exact approved cut. Tracks resolve BMap; animation strategy references provider patterns; sync is raw-based. Candidate evidence and approvals bind content/dependency hashes. No editing command keeps private timeline or approval truth, and no video-candidate human gate opens before current Watch plus candidate transcript analysis. Library administration uses its separate root/provider inventory and prepared-packet approvals; it never writes canonical timeline authority or starts BL-011 composition.

## Artistic briefing at authoring boundaries

Before proposing editorial structure, CMap cuts, BMap inserts, motion or sound direction, read the project's native `pipeline status` and matching `briefing.stageContexts` payload. Use the selected version's concrete treatment, scoped statements and exclusions. This is offered context, never edit/render approval. No selection means proceed with normal format diagnosis and current instructions; no artistic questionnaire or provider-history scan is mandatory. The brief index is the sole selection authority. Read [briefstart](references/briefstart.md) for raw, built-in, provider and personal-reference entry. A library folder proposal uses the organize inventory instead; indexing does not initialize a video's artistic briefing.
