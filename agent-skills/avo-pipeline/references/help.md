# /avo.help reference

Spoken alias: **`/avo --help`**. Cursor file: `commands/avo/help.md` → `/avo.help`.

## Full command index

### Discovery

| Command | When to use |
| ------- | ----------- |
| `/avo.help` | List all commands (this index) |
| `/avo.docs` | Open topic documentation |

### Guidelines (diagnose before editing)

| Command | When to use |
| ------- | ----------- |
| `/avo.guidelines --youtube` | YouTube format + playbooks |
| `/avo.guidelines --eq` | Audio EQ, restoration, loudness |
| `/avo.guidelines --tiktok` | TikTok vertical short-form |
| `/avo.guidelines --shorts` | YouTube Shorts |

### Pipeline stages

| Command | When to use |
| ------- | ----------- |
| `/avo.pipeline` | Full folder → master |
| `/avo.trim` | Cut only |
| `/avo.transcribe` | Transcribe only |
| `/avo.sound` | Mix, NR, SFX |
| `/avo.motion` | HyperFrames overlays |
| `/avo.captions` | Embedded captions (after overlays) |
| `/avo.watch` | watch-skill LOOP |

### Format orchestrators

| Command | When to use |
| ------- | ----------- |
| `/avo.shorts` | Orchestrated vertical Short workflow |
| `/avo.reframe` | Extract 9:16 clip from long-form master |
| `/avo.podcast-clip` | Podcast / interview clip extraction |
| `/avo.trailer` | Teaser / trailer from long-form master |

### Upload prep

| Command | When to use |
| ------- | ----------- |
| `/avo.chapters` | YouTube chapters from final transcript |
| `/avo.thumbnail` | Thumbnail candidate stills + checklist |

### QC & deliver

| Command | When to use |
| ------- | ----------- |
| `/avo.rights` | SOURCE-LOG, disclosure, reused-content audit |
| `/avo.audio-qc` | Master loudness / true peak delivery QC |
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

### Post-master ops

| Command | When to use |
| ------- | ----------- |
| `/avo.telemetry` | Disk/progress/ETA report |
| `/avo.learndown` | ai-memory consolidation |
| `/avo.cleanup` | Preserved-set delete + final wrap + stats record |
| `/avo.stats` | Local aggregate metrics (disk freed, videos completed) |

### Provider setup

| Command | When to use |
| ------- | ----------- |
| `/avo.provider` | Create or configure a provider (brand, manifest, scope) |

## Before any executing command

```text
Provider: <name>
The footage is at C:/path/to/footage
```

Content routers use `ProjectDir` + `Source` instead of footage when applicable.

Or, if the user opened the folder in the IDE: *The footage is in this folder.*

Shared args: [`arguments.md`](arguments.md) · User index: [`docs/avo-commands.md`](../../avo-commands.md)
