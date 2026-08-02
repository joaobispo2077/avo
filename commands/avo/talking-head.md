# /avo.talking-head Command

Orchestrator for talking-head graphic overlay packaging (not plain captions).

**Skill:** [`agent-skills/avo-pipeline/references/talking-head.md`](../../agent-skills/avo-pipeline/references/talking-head.md)

---

## Usage

```
/avo.talking-head
Provider: my-channel
rawDir: /path/to/footage
Footage: raw/interview-take.mp4
```

Optional: `--skip-motion` · `--preview` · `identity:` if captions also needed

---

## Role

Package existing talking-head clip with **designed graphic cards** via `talking-head-recut` — clip plays untouched underneath. Distinct from `/avo.captions` (spoken words only).

---

## Instructions

1. Parse `Provider`, `rawDir`, `Footage:` (required).
2. Load [`talking-head.md`](../../agent-skills/avo-pipeline/references/talking-head.md).
3. Route plain subtitles to `/avo.captions` if user intent is captions-only.
