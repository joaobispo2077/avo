# /avo.chapters Command

**Timeline integration:** Consumes

## Workflow guidance

**Workflow steps:** Validate chapters prerequisites → Run chapters → Verify and report the chapters result
**Step state source:** the consumed approved artifact, delivery-manifest.json when present, and the observed result
**Stopping conditions:** Missing required input, a failed or stale gate, a required human decision, or verified chapters completion
**Valid next commands:** /avo.deliver

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

YouTube chapter markers from the final-file transcript and approved structure.

**Skill:** [`agent-skills/avo-pipeline/references/chapters.md`](../../agent-skills/avo-pipeline/references/chapters.md)

---

## Usage

```
/avo.chapters
Provider: my-channel
rawDir: /path/to/footage
```

Optional: `Transcript:` path · `--preview` (draft titles only)

---

## Role

Produce upload-ready chapter timestamps at `<rawDir>/edit/delivery/chapters.txt`. Requires final master transcript — not rough-cut EDL alone.

---

## Instructions

1. Parse `Provider`, `rawDir`, optional transcript path.
2. Confirm final-file transcript under `edit/transcripts/`.
3. Follow [`chapters.md`](../../agent-skills/avo-pipeline/references/chapters.md).
4. First chapter must start at `0:00`.
5. Warn on Shorts profile or very short masters.

---

## Example

```text
/avo.chapters
Provider: my-channel
The footage is at C:/Videos/review
Transcript: edit/transcripts/20260801-review-master-v001.txt
```

## Shared timeline gateway

Resolves provider/video context and reads only exact approved lineage. It performs no canonical timeline mutation.
