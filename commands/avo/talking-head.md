# /avo.talking-head Command

**Timeline integration:** Profile

## Workflow guidance

**Workflow steps:** Validate talking head prerequisites → Run talking head → Verify and report the talking head result
**Step state source:** the child pipeline-run.json and its parent timeline lineage
**Stopping conditions:** Missing required input, a failed or stale gate, a required human decision, or verified talking head completion
**Valid next commands:** /avo.watch

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

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

## Shared timeline gateway

Runs the base pipeline with format-specific diagnosis and policy. It creates its own timeline context for derivatives and cannot bypass lineage, invalidation, Watch, transcript, or approval gates.
