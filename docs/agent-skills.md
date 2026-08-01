# AVO agent skills

AVO ships **three skills** for every supported agent. They install via the
[skills registry](https://www.npmjs.com/package/skills) (`npx skills add`) or the
unified installer (`bash install.sh`).

## Skills package

| Skill | Load when |
| ----- | --------- |
| **`avo`** | Any AVO editing session — rules, session start, hard constraints |
| **`avo-pipeline`** | Pipeline stages: transcribe, cut, sound, motion, watch, deliver |
| **`avo-provider`** | Create or configure a provider (brand, palette, manifest, scope) |

Registry: [`skills.json`](../skills.json) → paths under [`agent-skills/`](../agent-skills/).

## Install (all agents)

**Detect and install every agent on the machine:**

```bash
curl -fsSL https://raw.githubusercontent.com/joaobispo2077/avo/main/install.sh | bash
```

**One agent:**

```bash
npx skills add joaobispo2077/avo -a cursor
npx skills add joaobispo2077/avo -a claude
npx skills add joaobispo2077/avo -a codex
npx skills add joaobispo2077/avo -a windsurf
npx skills add joaobispo2077/avo -a cline
npx skills add joaobispo2077/avo -a gemini
npx skills add joaobispo2077/avo -a opencode
```

From a clone: `node bin/install.cjs --only cursor` (same three skills for each profile).

### Cursor-only: slash commands

Cursor also gets **`/avo.*`** commands copied to `.cursor/commands/avo/`:

```bash
cp -r commands/avo .cursor/commands/
```

Other agents use the **same workflows** by loading `avo-pipeline` and stating intent
in plain language (see [Use cases without slash commands](#use-cases-without-slash-commands)).

## Supported agents

| ID | Agent | Skills install | Slash commands |
| -- | ----- | -------------- | -------------- |
| `cursor` | Cursor | `npx skills add … -a cursor` | Yes (`/avo.*`) |
| `claude` | Claude Code | `-a claude` | No — load skills by name |
| `codex` | Codex CLI | `-a codex` | No |
| `windsurf` | Windsurf | `-a windsurf` | No |
| `cline` | Cline | `-a cline` | No |
| `gemini` | Gemini CLI | `-a gemini` | No |
| `opencode` | OpenCode | `-a opencode` | No |

Full matrix: [`install.md`](../install.md#tier-1--fast-agent-install).

### Offline / fallback copy

When `npx skills add` fails and you have a **local clone**, `bin/install.cjs`
copies every skill listed in `skills.json` from `agent-skills/` into the agent's
skills directory (e.g. `~/.claude/skills/`, `~/.cursor/skills/`, `~/.codex/skills/`).

## Use cases without slash commands

On non-Cursor agents, paste the **same intent** the slash command would take.
Use plain paths — you do not need the word `rawDir`:

```text
Load skill avo-pipeline. Run the full pipeline.
Provider: my-channel
The footage is at C:/Videos/my-first-edit
```

If you opened the folder in the agent already: *The footage is in this folder.*

Equivalent to `/avo.pipeline` on Cursor. Mapping table:
[`agent-skills/avo/references/use-cases.md`](../agent-skills/avo/references/use-cases.md).

## Per-use-case skill hints

| Goal | Skills | Cursor command |
| ---- | ------ | -------------- |
| New channel / brand | `avo-provider` | `/avo.provider` |
| Full folder → master | `avo`, `avo-pipeline` | `/avo.pipeline` |
| Cut only | `avo-pipeline` | `/avo.trim` |
| Transcribe only | `avo-pipeline` | `/avo.transcribe` |
| Captions + overlays | `avo-pipeline` + embedded-captions / talking-head-recut | `/avo.motion` |
| Format diagnosis | `avo-pipeline` | `/avo.guidelines --youtube` |
| After master | `avo-pipeline` | `/avo.learndown` then `/avo.cleanup` |

Extended prompts: [README use cases](../README.md#use-cases).

## Re-install / verify

```bash
node bin/install.cjs --dry-run --only claude
node bin/install.cjs --list
```

Uninstall: `npx skills remove joaobispo2077/avo -a cursor` (repeat per agent).
