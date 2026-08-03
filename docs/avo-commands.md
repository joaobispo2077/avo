# AVO slash commands

Pipeline-shaped entry points for Cursor and compatible agents. Each command needs
**Provider** and **where the footage lives** (plain path or “this folder”); the
agent maps that to `rawDir` internally.

Install Cursor commands (from AVO repo root):

```bash
mkdir -p .cursor/commands
cp -r commands/avo .cursor/commands/
```

Windows:

```powershell
New-Item -ItemType Directory -Force -Path .cursor/commands/avo | Out-Null
Copy-Item -Recurse commands/avo/* .cursor/commands/avo/
```

Gateway skill (agent auto-load): [`agent-skills/avo-pipeline/SKILL.md`](../agent-skills/avo-pipeline/SKILL.md)

Spoken alias: **`/avo --help`** → `/avo.help`

---

## Command index

### Discovery

| Command | Purpose |
| ------- | ------- |
| `/avo.help` | Master command index ([source](../commands/avo/help.md)) |
| `/avo.docs` | Route to topic docs ([source](../commands/avo/docs.md)) |
| `/avo.issues` | Prepare GitHub issue with environment context ([source](../commands/avo/issues.md)) |
| `/avo.supporters` | Sponsor links + backlog policy ([source](../commands/avo/supporters.md)) |
| `/avo.creators` | Creators showcase ([source](../commands/avo/creators.md)) |

### Guidelines

| Command | Purpose |
| ------- | ------- |
| `/avo.guidelines --youtube` | YouTube format diagnosis + playbooks ([source](../commands/avo/guidelines.md)) |
| `/avo.guidelines --eq` | Audio EQ, restoration, loudness |
| `/avo.guidelines --tiktok` | TikTok vertical short-form |
| `/avo.guidelines --shorts` | YouTube Shorts |
| `/avo.format` | Format diagnosis before edit ([source](../commands/avo/format.md)) |

### Pipeline

| Command | Purpose |
| ------- | ------- |
| `/avo.pipeline` | Full pipeline with Footage, SFX, B-roll, Music ([source](../commands/avo/pipeline.md)) |
| `/avo.trim` | Transcribe + cut only ([source](../commands/avo/trim.md)) |
| `/avo.transcribe` | Transcribe only, no cut ([source](../commands/avo/transcribe.md)) |
| `/avo.sync` | Audio sync diagnosis ([source](../commands/avo/sync.md)) |
| `/avo.sound` | Noise reduction, mix, SFX/Music ([source](../commands/avo/sound.md)) |
| `/avo.sound create` | Creative SFX brief ([reference](../agent-skills/avo-pipeline/references/sound-create.md)) |
| `/avo.audit` | Scoped QC ([source](../commands/avo/audit.md)) |
| `/avo.motion` | HyperFrames motion ([source](../commands/avo/motion.md)) |
| `/avo.captions` | Embedded captions after overlays ([source](../commands/avo/captions.md)) |
| `/avo.watch` | Full watch-skill LOOP ([source](../commands/avo/watch.md)) |

### Motion & composition

| Command | Purpose |
| ------- | ------- |
| `/avo.framework` | HyperFrames vs Remotion intake ([source](../commands/avo/framework.md)) |
| `/avo.motion-graphics` | Short motion graphic ([source](../commands/avo/motion-graphics.md)) |
| `/avo.general` | Custom HyperFrames composition ([source](../commands/avo/general.md)) |
| `/avo.remotion-port` | Remotion → HyperFrames port ([source](../commands/avo/remotion-port.md)) |
| `/avo.screencast` | Screencast + oversized cursor ([source](../commands/avo/screencast.md)) |

### Format orchestrators

| Command | Purpose |
| ------- | ------- |
| `/avo.shorts` | Orchestrated YouTube Shorts workflow ([source](../commands/avo/shorts.md)) |
| `/avo.reframe` | Vertical clip from long-form master ([source](../commands/avo/reframe.md)) |
| `/avo.podcast-clip` | Podcast / interview clip extraction ([source](../commands/avo/podcast-clip.md)) |
| `/avo.trailer` | Teaser / trailer from long-form master ([source](../commands/avo/trailer.md)) |
| `/avo.talking-head` | Talking-head graphic overlays ([source](../commands/avo/talking-head.md)) |

### Upload prep

| Command | Purpose |
| ------- | ------- |
| `/avo.chapters` | YouTube chapters from final transcript ([source](../commands/avo/chapters.md)) |
| `/avo.thumbnail` | Thumbnail candidate stills ([source](../commands/avo/thumbnail.md)) |
| `/avo.end-screen` | End-screen safe zone checklist ([source](../commands/avo/end-screen.md)) |

### QC & deliver

| Command | Purpose |
| ------- | ------- |
| `/avo.rights` | Rights and SOURCE-LOG audit ([source](../commands/avo/rights.md)) |
| `/avo.audio-qc` | Master loudness / true peak QC ([source](../commands/avo/audio-qc.md)) |
| `/avo.color` | Color / evidence QC ([source](../commands/avo/color.md)) |
| `/avo.grade` | Creative grade during edit ([source](../commands/avo/grade.md)) |
| `/avo.retention` | Retention diagnosis (no render) ([source](../commands/avo/retention.md)) |
| `/avo.animation-qc` | Motion render QC before composite ([source](../commands/avo/animation-qc.md)) |
| `/avo.audit` | Scoped QC window ([source](../commands/avo/audit.md)) |
| `/avo.deliver` | Full master QC + delivery manifest ([source](../commands/avo/deliver.md)) |

### Content (non-footage)

| Command | Purpose |
| ------- | ------- |
| `/avo.pr-video` | GitHub PR → explainer video ([source](../commands/avo/pr-video.md)) |
| `/avo.changelog-video` | Changelog → branded video ([source](../commands/avo/changelog-video.md)) |
| `/avo.explainer` | Article → faceless explainer ([source](../commands/avo/explainer.md)) |
| `/avo.slideshow` | Slide outline → HyperFrames slideshow ([source](../commands/avo/slideshow.md)) |
| `/avo.launch` | Product launch video ([source](../commands/avo/launch.md)) |
| `/avo.music-video` | Music → visual video ([source](../commands/avo/music-video.md)) |
| `/avo.figma` | Figma import ([source](../commands/avo/figma.md)) |
| `/avo.media` | Media catalog router ([source](../commands/avo/media.md)) |

Use `ProjectDir` + `Source` instead of footage paths — see [Shared arguments](#shared-arguments).

### Install & maintenance

| Command | Purpose |
| ------- | ------- |
| `/avo.update` | Refresh AVO from GitHub; full skills + toolchain sync; preserves your providers ([source](../commands/avo/update.md)) |
| `/avo.provider` | Create or configure a provider — brand, manifest, scope ([source](../commands/avo/provider.md)) |

Skill: [`avo-provider`](../agent-skills/avo-provider/SKILL.md) · Concept: [`docs/providers.md`](providers.md)

### Post-master ops

| Command | Purpose |
| ------- | ------- |
| `/avo.telemetry` | Disk/progress/ETA report ([source](../commands/avo/telemetry.md)) |
| `/avo.learndown` | ai-memory consolidation + draft wrap ([source](../commands/avo/learndown.md)) |
| `/avo.cleanup` | Preserved-set cleanup + final wrap + stats record ([source](../commands/avo/cleanup.md)) |
| `/avo.stats` | Local aggregate metrics ([source](../commands/avo/stats.md)) |

Shipped command files: [`../commands/avo/`](../commands/avo/) (46 commands)

---

## Shared arguments

```text
Provider: my-channel
The footage is at C:/Videos/my-edit
Footage: C:/Videos/my-edit/raw/main.mp4
SFX: D:/assets/sfx/
B-roll: D:/assets/broll/
Music: D:/assets/music/
from: 9:30
to: 9:35
ProjectDir: /path/to/hyperframes-project
Source: https://github.com/owner/repo/pull/123
```

Say **this folder** when you already opened the footage directory in Cursor.
Power users may still write `rawDir: /abs/path`.

Full schema: [`../agent-skills/avo-pipeline/references/arguments.md`](../agent-skills/avo-pipeline/references/arguments.md)

---

## Quick examples

**Help:**

```text
/avo.help
```

**Guidelines before a review:**

```text
/avo.guidelines --youtube
Provider: my-gaming-channel
The footage is at C:/Videos/review-001
```

**Transcribe only:**

```text
/avo.transcribe
Provider: my-channel
The footage is at C:/Videos/review
Footage: C:/Videos/review/raw/take.mp4
```

**Full pipeline:**

```text
/avo.pipeline
Provider: my-channel
The footage is at C:/Videos/review
Footage: C:/Videos/review/raw/take.mp4
SFX: D:/assets/sfx/
Music: D:/assets/music/
```

**After master approved:**

```text
/avo.learndown
Provider: my-channel
The footage is at C:/Videos/review

/avo.cleanup
The footage is at C:/Videos/review

/avo.stats
```

**Captions on approved edit:**

```text
/avo.captions
Provider: my-channel
The footage is at C:/Videos/review
identity: anchor
```

**Shorts (native vertical):**

```text
/avo.shorts
Provider: my-channel
The footage is at C:/Videos/short-001
identity: anchor
```

**Deliver before upload:**

```text
/avo.rights
Provider: my-channel
The footage is at C:/Videos/review

/avo.audio-qc
Provider: my-channel
The footage is at C:/Videos/review
Footage: edit/masters/20260801-review-master-v001.mp4

/avo.deliver
Provider: my-channel
The footage is at C:/Videos/review
```

---

Pipeline detail: [`avo-workflow.md`](avo-workflow.md) · Canonical rules: [`../AGENTS.md`](../AGENTS.md)
