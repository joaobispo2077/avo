# AVO install

Two tiers: **Tier 1** installs agent skills + slash commands in ~30 seconds. **Tier 2** prepares the full local toolchain (ffmpeg, whisper, watch-skill, HyperFrames). User-facing summary: [README § Install](../../README.md#install).

---

## Tier 1 — Fast agent install

### One command (every agent)

**macOS · Linux · WSL · Git Bash**

```bash
curl -fsSL https://raw.githubusercontent.com/joaobispo2077/avo/main/scripts/install/install.sh | bash
```

**Windows · PowerShell 5.1+**

```powershell
irm https://raw.githubusercontent.com/joaobispo2077/avo/main/scripts/install/install.ps1 | iex
```

~30 seconds. Needs **Node ≥18**. Detects agents on your machine. Skips agents you do not have. Safe to re-run.

#### What tier 1 installs

- **Skills (all agents):** `avo`, `avo-pipeline`, `avo-provider` via [`skills.json`](../../skills.json) / the skills registry
- **Cursor only:** slash commands `commands/avo/` → `.cursor/commands/avo/`

Details: [`docs/agent-skills.md`](../agent-skills.md).

#### Full toolchain (tier 2)

Re-run with `--full` after cloning, or jump to [Tier 2 — Full toolchain setup](#tier-2--full-toolchain-setup):

```bash
bash scripts/install/install.sh --full --lang en
pwsh scripts/install/install.ps1 -Full -Lang en
```

### One agent only

```bash
npx skills add joaobispo2077/avo -a cursor
npx skills add joaobispo2077/avo -a claude
npx skills add joaobispo2077/avo -a codex
npx skills add joaobispo2077/avo -a windsurf
npx skills add joaobispo2077/avo -a cline
npx skills add joaobispo2077/avo -a gemini
npx skills add joaobispo2077/avo -a opencode
```

Copy slash commands manually (Cursor):

```bash
mkdir -p .cursor/commands
cp -r commands/avo .cursor/commands/
```

Windows:

```powershell
New-Item -ItemType Directory -Force -Path .cursor/commands/avo | Out-Null
Copy-Item -Recurse commands/avo/* .cursor/commands/avo/
```

### Supported agents

| ID | Agent | Detect | Install |
| -- | ----- | ------ | ------- |
| `cursor` | Cursor | `cursor` CLI, Cursor.app, `~/.cursor` | 3 skills + `/avo.*` commands |
| `claude` | Claude Code | `claude` CLI, `~/.claude` | 3 skills (+ fallback copy from clone) |
| `codex` | Codex CLI | `codex` on PATH | 3 skills |
| `windsurf` | Windsurf | `windsurf` CLI | 3 skills |
| `cline` | Cline | VS Code / Cursor Cline extension | 3 skills |
| `gemini` | Gemini CLI | `gemini` on PATH | 3 skills |
| `opencode` | OpenCode | `opencode` on PATH | 3 skills |

When `npx skills add` fails, a local clone can copy all entries from `skills.json`
into the agent skills directory (see [`docs/agent-skills.md`](../agent-skills.md)).

List IDs: `node bin/install.cjs --list`

### Tier 1 flags

| Flag | Meaning |
| ---- | ------- |
| `--dry-run` | Print actions only |
| `--full` | Also run toolchain setup |
| `--lang CODE` | Transcription language for `--full` (`en`, `pt`, …) |
| `--only AGENT` | Install for one agent |
| `--list` | Print supported agent IDs |
| `--yes` / `-y` | Non-interactive |
| `--uninstall` | Best-effort remove (skills CLI) |
| `-h` / `--help` | Help |

From a clone:

```bash
node bin/install.cjs --dry-run
npm run install:agents -- --only cursor
```

### Environment

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `AVO_INSTALL_REPO` | `joaobispo2077/avo` | GitHub slug for npx / raw URLs |
| `AVO_INSTALL_REF` | `main` | Git ref for pinned fetch |

### Uninstall

Best-effort per agent (skills CLI varies by version):

```bash
npx skills remove joaobispo2077/avo -a cursor
```

Remove Cursor commands:

```bash
rm -rf .cursor/commands/avo
rm -rf ~/.cursor/commands/avo
```

### Troubleshooting

**Node too old:** Upgrade to Node ≥18 from [nodejs.org](https://nodejs.org).

**No agents detected:** Install Cursor (or your agent) first, or use `--only cursor`.

**curl pipe fails:** Clone the repo and run `bash scripts/install/install.sh` locally.

**Need ffmpeg / whisper:** Tier 1 is agent brain only. Run `bash scripts/install/install.sh --full --lang en` from a clone.

**Install broke?** Open your agent in the AVO repo and say: *"Read docs/install/README.md and install AVO for me."*

### Local clone (developers)

```bash
git clone https://github.com/joaobispo2077/avo.git
cd avo
bash scripts/install/install.sh --dry-run
bash scripts/install/install.sh --only cursor
bash scripts/install/install.sh --full --lang en
```

Installer scripts live in [`scripts/install/`](../../scripts/install/).

---

## Tier 2 — Full toolchain setup

AVO orchestrates independent local tools. This section is the **toolchain setup contract**
(full ffmpeg, whisper, watch-skill, HyperFrames).

`AGENTS.md` is canonical; do not contradict it. Pipeline detail: [`docs/avo-workflow.md`](../avo-workflow.md).

> Historical context: AVO started as a fork of `browser-use/video-use` and grew
> into an orchestrator over video-use, watch-skill, HyperFrames, Remotion, GitHub Spec Kit,
> ai-memory, and ai-jail. Setup prepares that toolchain — it does not replace any
> one engine.

### Required end state

1. The repository is cloned at a stable path (`git clone https://github.com/joaobispo2077/avo.git`).
2. Python 3.10+ dependencies are installed (video-use engine).
3. `ffmpeg` and `ffprobe` are on `PATH` (Node `ffmpeg-static`/`ffprobe-static`
   are a fallback).
4. A **multilingual** faster-whisper model is prepared locally; the transcription
   **language is chosen at setup** (`--lang`), not fixed to any locale.
5. Node.js ≥ 18 with the motion toolchain (HyperFrames) installed.
6. [GitHub Spec Kit](https://github.com/github/spec-kit) present (`.specify` marker).
7. Optional: watch-skill, ai-memory, ai-jail, logo-generator-skill.

No transcription account or credential is part of local setup. Optional hosted
alternatives are opt-in and configured separately (see the README tool-routing
table).

### One command per OS

The native scripts are the **primary** entrypoint. Both accept identical
`--flag value` options.

```powershell
# Windows / WSL-from-PowerShell
pwsh scripts/setup.ps1 --lang pt [--with-memory] [--with-jail] [--with-logo] [--skip TOOL]
# No pwsh? Windows PowerShell 5.1 works too (scripts are 5.1-safe):
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1 --lang pt
```

```bash
# macOS / Linux / WSL
bash scripts/setup.sh --lang pt [--with-memory] [--with-jail] [--with-logo] [--skip TOOL]
```

```bash
# Cross-platform wrapper (dispatches to the native script via cross-env)
npm run setup -- --lang pt --with-memory
```

#### Setup flags

| Flag | Meaning |
| --- | --- |
| `--lang CODE` | faster-whisper transcription language (e.g. `pt`, `en`, `es`). Prompted if omitted. |
| `--model SIZE` | Whisper model size to prepare (default `small`). |
| `--with-memory` | Install [ai-memory](https://github.com/akitaonrails/ai-memory) (optional; zero-LLM by default). |
| `--with-jail` | Install [ai-jail](https://github.com/akitaonrails/ai-jail) (optional agent sandbox; **WSL-only on Windows**). |
| `--with-logo` | Install [logo-generator-skill](https://github.com/op7418/logo-generator-skill) (optional). |
| `--skip TOOL` | Skip a step: `speckit`, `engine`, `watch`, `hyperframes`, `remotion` (repeatable). |
| `--yes` / `-y` | Non-interactive; accept defaults. |
| `--dry-run` | Print every action without executing (safe to inspect first). |

### What setup prepares (in order)

1. **Preflight** — detects OS/WSL, checks `python`, `node`, `npm`, `git`.
2. **GitHub Spec Kit** — verifies the `.specify` directory is present (installed via `specify init` or bundled with AVO).
3. **video-use engine** — `uv sync` (or `pip install -e .`), verifies
   `ffmpeg`/`ffprobe`, records the chosen language in `.avo/state.json`, and
   prepares the Whisper model via `avo.prepare_transcription`.
4. **watch-skill** — clones/updates `oxbshw/watch-skill` into `tools/`.
5. **HyperFrames** — `npm install` + `hyperframes doctor`.
6. **Remotion** — installed per-project when justified (see
   `docs/remotion-decision-guide.md`).
7. **ai-memory** *(with `--with-memory`)* — clones `akitaonrails/ai-memory`.
8. **ai-jail** *(with `--with-jail`)* — installs via `brew`/`cargo`/`mise`/`nix`
   (Linux/macOS) or inside **WSL** on Windows.
9. **logo-generator-skill** *(with `--with-logo`)*.

Each step prints a pass/fail row. Required steps (`python`, `engine`) fail the
run; optional tools only `WARN`. The script is **idempotent** — re-running skips
satisfied steps.

### Language / model notes

- The engine requires a **multilingual** model. English-only `.en` variants are
  rejected; pick a multilingual size (`small`, `medium`, `large-v3`, …).
- The default model directory is `~/.cache/video-use/models/<size>`. Set
  `VIDEO_USE_MODEL_DIR` to relocate the shared model root, or pass
  `--model-dir` to `avo.prepare_transcription`.

### Verify

```bash
# Gate 1 — orchestrator prerequisites (video-use, watch-skill, HyperFrames, …)
npm run validate:prerequisites -- --ci

# Gate 2 — project usability (run after Gate 1 passes)
npm run validate:usability -- --ci

After your first video project starts, expect **approval gates**: when watch-skill and
transcription analysis finish a stage, review files in `edit/preview/` and
`edit/review/` before the agent promotes resolution. See [`docs/avo-workflow.md`](../avo-workflow.md) §4b.

python -m avo.prepare_transcription --help
python -m avo.transcribe --help
ffprobe -version
pytest
```

Agent-facing CI detail: [`docs/ci.md`](../ci.md).

To confirm the offline/no-download behavior, point `--model-dir` at an empty
directory: transcription must fail fast with the preparation command and must
not download.
