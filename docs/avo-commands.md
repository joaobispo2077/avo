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

### Guidelines

| Command | Purpose |
| ------- | ------- |
| `/avo.guidelines --youtube` | YouTube format diagnosis + playbooks ([source](../commands/avo/guidelines.md)) |
| `/avo.guidelines --eq` | Audio EQ, restoration, loudness |
| `/avo.guidelines --tiktok` | TikTok vertical short-form |
| `/avo.guidelines --shorts` | YouTube Shorts |

### Pipeline

| Command | Purpose |
| ------- | ------- |
| `/avo.pipeline` | Full pipeline with Footage, SFX, B-roll, Music ([source](../commands/avo/pipeline.md)) |
| `/avo.trim` | Transcribe + cut only ([source](../commands/avo/trim.md)) |
| `/avo.transcribe` | Transcribe only, no cut ([source](../commands/avo/transcribe.md)) |
| `/avo.sound` | Noise reduction, mix, SFX/Music ([source](../commands/avo/sound.md)) |
| `/avo.sound create` | Creative SFX brief ([reference](../agent-skills/avo-pipeline/references/sound-create.md)) |
| `/avo.audit` | Scoped QC ([source](../commands/avo/audit.md)) |
| `/avo.watch` | Full watch-skill LOOP ([source](../commands/avo/watch.md)) |
| `/avo.motion` | HyperFrames motion ([source](../commands/avo/motion.md)) |
| `/avo.captions` | Embedded captions after overlays ([source](../commands/avo/captions.md)) |
| `/avo.deliver` | Full master QC + delivery manifest ([source](../commands/avo/deliver.md)) |
| `/avo.shorts` | Orchestrated YouTube Shorts workflow ([source](../commands/avo/shorts.md)) |
| `/avo.reframe` | Vertical clip from long-form master ([source](../commands/avo/reframe.md)) |

### Post-master ops

| Command | Purpose |
| ------- | ------- |
| `/avo.telemetry` | Disk/progress/ETA report ([source](../commands/avo/telemetry.md)) |
| `/avo.learndown` | ai-memory consolidation + draft wrap ([source](../commands/avo/learndown.md)) |
| `/avo.cleanup` | Preserved-set cleanup + final wrap + stats record ([source](../commands/avo/cleanup.md)) |
| `/avo.stats` | Local aggregate metrics ([source](../commands/avo/stats.md)) |

### Provider setup

| Command | Purpose |
| ------- | ------- |
| `/avo.provider` | Create or configure a provider — brand, manifest, scope ([source](../commands/avo/provider.md)) |

Skill: [`avo-provider`](../agent-skills/avo-provider/SKILL.md) · Concept: [`docs/providers.md`](providers.md)

Shipped command files: [`../commands/avo/`](../commands/avo/) (20 commands)

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
/avo.deliver
Provider: my-channel
The footage is at C:/Videos/review
```

---

Pipeline detail: [`avo-workflow.md`](avo-workflow.md) · Canonical rules: [`../AGENTS.md`](../AGENTS.md)
