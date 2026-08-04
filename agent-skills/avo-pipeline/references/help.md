# /avo.help reference

Spoken alias: **`/avo --help`**. Cursor file: `commands/avo/help.md` → `/avo.help`.

## Full command index

### Discovery

| Command | When to use |
| ------- | ----------- |
| `/avo.help` | List all commands (this index) |
| `/avo.docs` | Open topic documentation |
| `/avo.issues` | Prepare a GitHub issue (environment + template chooser) |
| `/avo.supporters` | Sponsor links + backlog prioritization policy |
| `/avo.creators` | Curated channels using AVO |

### Guidelines (diagnose before editing)

| Command | When to use |
| ------- | ----------- |
| `/avo.guidelines --youtube` | YouTube format + playbooks |
| `/avo.guidelines --eq` | Audio EQ, restoration, loudness |
| `/avo.guidelines --tiktok` | TikTok vertical short-form |
| `/avo.guidelines --shorts` | YouTube Shorts |
| `/avo.format` | Per-project format diagnosis (before edit) |

### Pipeline stages

| Command | When to use |
| ------- | ----------- |
| `/avo.pipeline` | Full folder → master |
| `/avo.trim` | Cut only |
| `/avo.voiceover` | Lite concat + external VO (no motion) |
| `/avo.transcribe` | Transcribe only |
| `/avo.sync` | Audio sync diagnosis (before long/external cuts) |
| `/avo.sound` | Mix, NR, SFX |
| `/avo.motion` | HyperFrames overlays |
| `/avo.captions` | Embedded captions (after overlays) |
| `/avo.watch` | watch-skill LOOP |

### Motion & composition

| Command | When to use |
| ------- | ----------- |
| `/avo.framework` | HyperFrames vs Remotion intake before motion |
| `/avo.motion-graphics` | Short design-led motion graphic |
| `/avo.general` | Custom HyperFrames composition |
| `/avo.remotion-port` | Remotion → HyperFrames port |
| `/avo.screencast` | Tutorial screencast + oversized cursor |

### Format orchestrators

| Command | When to use |
| ------- | ----------- |
| `/avo.shorts` | Orchestrated vertical Short workflow |
| `/avo.reframe` | Extract 9:16 clip from long-form master |
| `/avo.podcast-clip` | Podcast / interview clip extraction |
| `/avo.trailer` | Teaser / trailer from long-form master |
| `/avo.talking-head` | Graphic overlay packaging (talking-head-recut) |

### Upload prep

| Command | When to use |
| ------- | ----------- |
| `/avo.chapters` | YouTube chapters from final transcript |
| `/avo.thumbnail` | Thumbnail candidate stills + checklist |
| `/avo.end-screen` | End-screen safe zone + asset checklist |

### QC & deliver

| Command | When to use |
| ------- | ----------- |
| `/avo.rights` | SOURCE-LOG, disclosure, reused-content audit |
| `/avo.audio-qc` | Master loudness / true peak delivery QC |
| `/avo.color` | Color / evidence integrity QC |
| `/avo.grade` | Creative grade pass (`grade.py`) during edit |
| `/avo.retention` | Pre-publish retention diagnosis (no render) |
| `/avo.animation-qc` | Motion render QC before composite |
| `/avo.audit` | Scoped QC window |
| `/avo.deliver` | Full master QC + delivery manifest |

### Content

| Command | When to use |
| ------- | ----------- |
| `/avo.pr-video` | GitHub PR → explainer video |
| `/avo.changelog-video` | Changelog markdown → branded video |
| `/avo.explainer` | Article / notes → faceless explainer |
| `/avo.slideshow` | Slide outline → HyperFrames slideshow |
| `/avo.launch` | Product / marketing URL → launch video |
| `/avo.music-video` | Music track → visual video |
| `/avo.figma` | Figma → HyperFrames import |
| `/avo.media` | Catalog BGM/SFX/logos via media-use |

### Install & maintenance

| Command | When to use |
| ------- | ----------- |
| `/avo.update` | Refresh AVO from GitHub; skills + toolchain; preserves providers |
| `/avo.provider` | Create or configure a provider (brand, manifest, scope) |

### Post-master ops

| Command | When to use |
| ------- | ----------- |
| `/avo.telemetry` | Disk/progress/ETA report |
| `/avo.learndown` | Iteration condensation + optional ai-memory; see [`docs/ai-memory-and-ai-jail.md`](../../../docs/ai-memory-and-ai-jail.md) |
| `/avo.cleanup` | Preserved-set delete + final wrap + stats record |
| `/avo.stats` | Local aggregate metrics (disk freed, videos completed) |

## Before any executing command

```text
Provider: <name>
The footage is at C:/path/to/footage
```

Content routers use `ProjectDir` + `Source` instead of footage when applicable.

Or, if the user opened the folder in the IDE: *The footage is in this folder.*

Shared args: [`arguments.md`](arguments.md) · User index: [`docs/avo-commands.md`](../../avo-commands.md)
