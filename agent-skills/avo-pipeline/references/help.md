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
| `/avo.audit` | Scoped QC window |
| `/avo.deliver` | Full master QC + delivery manifest |

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

Or, if the user opened the folder in the IDE: *The footage is in this folder.*

Shared args: [`arguments.md`](arguments.md) · User index: [`docs/avo-commands.md`](../../avo-commands.md)
