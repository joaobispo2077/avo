---
name: avo-pipeline
description: Gateway for AVO slash commands (/avo.help, /avo.guidelines, /avo.pipeline, /avo.trim, /avo.transcribe, /avo.sound, /avo.sync, /avo.audit, /avo.watch, /avo.motion, /avo.captions, /avo.talking-head, /avo.rights, /avo.audio-qc, /avo.color, /avo.grade, /avo.format, /avo.framework, /avo.chapters, /avo.thumbnail, /avo.end-screen, /avo.deliver, /avo.shorts, /avo.reframe, /avo.podcast-clip, /avo.trailer, /avo.pr-video, /avo.changelog-video, /avo.explainer, /avo.slideshow, /avo.launch, /avo.music-video, /avo.figma, /avo.media, /avo.motion-graphics, /avo.general, /avo.remotion-port, /avo.screencast, /avo.retention, /avo.animation-qc, /avo.telemetry, /avo.learndown, /avo.cleanup, /avo.stats, /avo.docs). Load when the user invokes any /avo.* command or declares Footage/rawDir asset paths.
---

# AVO pipeline commands (gateway)

Entry skill for **`/avo.*`** slash commands. Canonical rules: [`AGENTS.md`](../../AGENTS.md), [`SKILL.md`](../../SKILL.md), [`docs/avo-workflow.md`](../../docs/avo-workflow.md).

## Command router

| User invokes | Read |
| ------------ | ---- |
| `/avo.help` (alias `/avo --help`) | [`references/help.md`](references/help.md) |
| `/avo.guidelines --youtube` | [`references/guidelines-youtube.md`](references/guidelines-youtube.md) |
| `/avo.guidelines --eq` | [`references/guidelines-eq.md`](references/guidelines-eq.md) |
| `/avo.guidelines --tiktok` | [`references/guidelines-tiktok.md`](references/guidelines-tiktok.md) |
| `/avo.guidelines --shorts` | [`references/guidelines-shorts.md`](references/guidelines-shorts.md) |
| `/avo.guidelines` (no flag) | [`references/guidelines.md`](references/guidelines.md) |
| `/avo.docs` | [`references/docs.md`](references/docs.md) |
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
| `/avo.stats` | [`references/stats.md`](references/stats.md) |
| `/avo.provider` | [`references/provider.md`](references/provider.md) — load skill **`avo-provider`** |

Always parse shared args first: [`references/arguments.md`](references/arguments.md). Full map: [`references/command-map.md`](references/command-map.md).

## Non-negotiable

1. Declare `provider` + `rawDir` before any stage.
2. Human approval gates after watch-skill + transcription analysis (see workflow §4b).
3. Subtitles last in filter chain; 30ms audio fades at cuts.
4. Session outputs only under `<rawDir>/edit/`.

## Install (Cursor)

Copy shipped commands into your project or user config:

```bash
# from AVO repo root
cp -r commands/avo .cursor/commands/
```

Or install per [`docs/avo-commands.md`](../../docs/avo-commands.md).
