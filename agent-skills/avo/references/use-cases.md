# Use case → skill / command map

Load **`avo`** for every session. Add **`avo-pipeline`** for pipeline work.
Add **`avo-provider`** when setting up a channel before the first video.

## Cursor slash commands

| Goal | Command |
| ---- | ------- |
| Full folder → master | `/avo.pipeline` |
| Cut + transcribe, no motion | `/avo.trim` |
| Transcribe only | `/avo.transcribe` |
| Mix / noise reduction | `/avo.sound` |
| HyperFrames overlays | `/avo.motion` |
| watch-skill LOOP | `/avo.watch` |
| Scoped QC window | `/avo.audit` |
| YouTube format rules | `/avo.guidelines --youtube` |
| Shorts / TikTok | `/avo.guidelines --shorts` or `--tiktok` |
| Create provider | `/avo.provider` |
| After master approved | `/avo.learndown` then `/avo.cleanup` |
| Command index | `/avo.help` |

## Non-Cursor agents (plain language)

Say the command name and args — the agent should load **`avo-pipeline`**:

```text
Load avo-pipeline. Run trim (transcribe + cut, no motion).
Provider: my-channel
The footage is at C:/Videos/my-edit
```

## All use cases ([README § Use cases](../../../README.md#use-cases))

| Use case | Skills | Cursor |
| -------- | ------ | ------ |
| Product review + spec cards | `avo`, `avo-pipeline` | `/avo.pipeline` |
| Pet promo + logo + CTA | `avo`, `avo-pipeline`, `avo-provider` if new | `/avo.pipeline` |
| Dealer walkthrough | `avo`, `avo-pipeline` | `/avo.trim` + `/avo.motion` |
| Game review | `avo`, `avo-pipeline` | `/avo.pipeline` |
| Tech first impression | `avo`, `avo-pipeline` | `/avo.pipeline` |
| Live pipeline demo + deep motion | `avo`, `avo-pipeline` | `/avo.pipeline` + [`animation-direction.md`](../../../specs/active/avo-pipeline-demo-motion/animation-direction.md) |
| Health / physio comparison | `avo`, `avo-pipeline` | `/avo.trim` or `/avo.pipeline` |
| Going global (backlog) | `avo`, `avo-pipeline` | `/avo.pipeline` after master |

## Caption / motion skills (repo `.claude/skills/` or project skills)

These are separate from the AVO package but pair with `/avo.motion`:

| Style | Skill / identity |
| ----- | ---------------- |
| Clean YouTube | embedded-captions `anchor` |
| Keynote / launch | `keynote` |
| Gaming | `nightcity` or `scoreboard` |
| Documentary | `documentary` |
| Spec readout | `terminal` |
| Glass cards | talking-head-recut + HyperFrames |

Install full toolchain for motion: `bash scripts/install/install.sh --full --lang en`.
