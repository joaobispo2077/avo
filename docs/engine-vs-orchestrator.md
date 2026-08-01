# AVO vs video-use engine

AVO is the **orchestrator**. [video-use](https://github.com/browser-use/video-use) is the
**editing engine** it routes to for transcription, cuts, captions, and delivery helpers.

This repo is **`joaobispo2077/avo`**, not the upstream video-use project.

---

## Roles

| Name | What it is | Where it lives |
| ---- | ---------- | -------------- |
| **AVO** | AI Video Orchestrator — agent skills, slash commands, provider model, routing, gates, docs | This repo |
| **AVO Python engine** | Local helpers for transcribe, EDL, grade, render (`helpers/`, `pyproject.toml`) | Bundled in this repo (fork lineage from video-use) |
| **video-use (upstream)** | Open-source conversation-driven editing project | [browser-use/video-use](https://github.com/browser-use/video-use) |

AVO **uses** the engine; it is not interchangeable with upstream video-use as a product name.

---

## Where you still see "video-use"

These are **intentional** — they name the engine or upstream credit, not the orchestrator:

| Context | Example | Why keep |
| ------- | ------- | -------- |
| README fork + Built on | link to `browser-use/video-use` | Upstream credit |
| Routing table / `avo.config.json` | `video-use+faster-whisper` | Stage owner in the pipeline |
| Setup scripts | step "video-use engine" | Describes Python deps + ffmpeg + Whisper prep |
| Model cache | `~/.cache/video-use/models`, `AVO_MODEL_DIR`, `VIDEO_USE_MODEL_DIR` | Runtime compat; prefer `AVO_MODEL_DIR` |
| Gate 1 manifest | `avo-engine` in `avo.dependencies.json` (alias: `video-use-engine`) | Internal dependency ID |

---

## Where we say AVO instead

Product-facing copy uses **AVO** for session outputs, constitution, package name (`avo`),
and workflow diagrams — even when the underlying code path is the bundled engine.

---

## Footage never lives in this repo

All session outputs go under `<footage>/edit/`, declared via `avo.project.json` and
provider manifests. See [`repo-layout.md`](repo-layout.md).
