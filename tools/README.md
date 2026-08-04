# External tools (install-time)

This directory holds **cloned orchestrator dependencies**, not AVO source code.
Setup populates it; nothing here is committed except this README.

---

## Bundled engine vs cloned tools

**video-use is a core dependency — but it does not live under `tools/`.**

After the fork, the editing engine was **bundled into this repo** as the **AVO Python
engine** (`src/avo/`, `pyproject.toml`, `uv.lock`). Gate 1 validates it in-tree via
**`avo-engine`** in [`avo.dependencies.json`](../config/avo.dependencies.json) (alias:
`video-use-engine`) — not as a git clone.

| Component | What it is | Where it lives |
| --- | --- | --- |
| **AVO orchestrator** | Agent skills, routing, gates, provider model | Repo root (`agent-skills/`, `docs/`, `scripts/`) |
| **AVO Python engine** | Transcribe, EDL, grade, render (fork lineage from video-use) | **`helpers/` + `pyproject.toml`** (bundled) |
| **Upstream video-use** | Original open-source project | [browser-use/video-use](https://github.com/browser-use/video-use) — credit only |

See [`docs/engine-vs-orchestrator.md`](../docs/engine-vs-orchestrator.md) for naming rules
(AVO product vs engine vs upstream credit).

Routing still labels the transcribe stage `video-use+faster-whisper` in
[`avo.config.json`](../config/avo.config.json) — that names the **engine role**, not a path under
`tools/`.

Model cache (runtime): `~/.cache/video-use/models` (compat from fork; env
`AVO_MODEL_DIR` or `VIDEO_USE_MODEL_DIR`).

---

## Cloned dependencies (this directory)

| Path | Installed by | Upstream |
| ---- | ------------ | -------- |
| `watch-skill/` | `scripts/setup.sh` (required) | [oxbshw/watch-skill](https://github.com/oxbshw/watch-skill) |
| `ai-memory/` | `--with-memory` (clone only) | [akitaonrails/ai-memory](https://github.com/akitaonrails/ai-memory) — runtime install: [`docs/ai-memory-and-ai-jail.md`](../docs/ai-memory-and-ai-jail.md) |
| `logo-generator-skill/` | `--with-logo` | [op7418/logo-generator-skill](https://github.com/op7418/logo-generator-skill) |
| `ai-jail/` | `--with-jail` (optional binary) | [akitaonrails/ai-jail](https://github.com/akitaonrails/ai-jail) — Linux/macOS native, WSL2 on Windows |

Run setup from the repo root:

```bash
bash scripts/setup.sh --lang en
```

Gate 1 validates clones via [`avo.dependencies.json`](../config/avo.dependencies.json) and the
bundled **avo-engine** via `pyproject.toml` + `helpers/` (`avo-engine` in manifest).

### Optional upstream reference (maintainers)

Sync upstream [browser-use/video-use](https://github.com/browser-use/video-use) for diffs only:

```bash
bash scripts/upstream/sync-video-use-upstream.sh
python scripts/upstream/diff-engine-helpers.py
# or: bash scripts/setup.sh --with-upstream-ref
```

Output: [`specs/upstream-diffs/video-use/`](../specs/upstream-diffs/video-use/README.md).
Clone lives at `tools/video-use-upstream/` (gitignored).
