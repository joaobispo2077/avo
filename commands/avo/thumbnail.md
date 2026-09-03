# /avo.thumbnail Command

**Timeline integration:** Consumes

## Workflow guidance

**Workflow steps:** Validate thumbnail prerequisites → Run thumbnail → Verify and report the thumbnail result
**Step state source:** the consumed approved artifact, delivery-manifest.json when present, and the observed result
**Stopping conditions:** Missing required input, a failed or stale gate, a required human decision, or verified thumbnail completion
**Valid next commands:** /avo.deliver

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

Frame candidates and safe-zone checklist from the approved master (ffmpeg stills v1).

**Skill:** [`agent-skills/avo-pipeline/references/thumbnail.md`](../../agent-skills/avo-pipeline/references/thumbnail.md)

---

## Usage

```
/avo.thumbnail
Provider: my-channel
rawDir: /path/to/footage
Footage: edit/masters/20260801-review-master-v001.mp4
```

Optional: `--count 3` (default ≥3 frames)

---

## Role

Extract truthful candidate stills to `<rawDir>/edit/delivery/thumbnails/` with provider design checks. No mandatory HyperFrames render in v1.

---

## Instructions

1. Parse `Provider`, `rawDir`, optional master path.
2. Require approved master export.
3. Follow [`thumbnail.md`](../../agent-skills/avo-pipeline/references/thumbnail.md).
4. **Wait for user approval** before marking candidates final.

---

## Example

```text
/avo.thumbnail
Provider: my-channel
The footage is at C:/Videos/review
```

## Shared timeline gateway

Resolves provider/video context and reads only exact approved lineage. It performs no canonical timeline mutation.
