# /avo.beat-edit Command

**Timeline integration:** Profile

## Workflow guidance

**Workflow steps:** Validate beat-edit prerequisites → Map reference or generate from inserts → Verify and report the beat-edit result
**Step state source:** the child pipeline-run.json and its parent timeline lineage
**Stopping conditions:** Missing required input, a failed or stale gate, a required human decision, or verified beat-edit completion
**Valid next commands:** /avo.watch

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

Router to beat-synced insert-edit workflow (map a reference, then generate from music + clips/images/GIFs).

**Skill:** [`agent-skills/avo-pipeline/references/beat-edit.md`](../../agent-skills/avo-pipeline/references/beat-edit.md)

---

## Usage

```
/avo.beat-edit
Provider: my-channel
ProjectDir: /path/to/footage
Reference: /path/to/reference-edit.mp4
Source: /path/to/track.mp3
Inserts: /path/to/inserts-folder
```

Map-only: omit `Source` / `Inserts`. Generate-only: omit `Reference` and pass an approved `--map` (or use the starter map).

---

## Instructions

1. Parse `Provider`, `ProjectDir` (`rawDir`), optional `Reference`, `Source` (music bed), and `Inserts`.
2. Follow [`beat-edit.md`](../../agent-skills/avo-pipeline/references/beat-edit.md).

## Shared timeline gateway

Runs the base pipeline with format-specific diagnosis and policy. It creates its own timeline context for derivatives and cannot bypass lineage, invalidation, Watch, transcript, or approval gates.
