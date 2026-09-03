# /avo.reframe Command

**Timeline integration:** Profile

## Workflow guidance

**Workflow steps:** Validate reframe prerequisites → Run reframe → Verify and report the reframe result
**Step state source:** the child pipeline-run.json and its parent timeline lineage
**Stopping conditions:** Missing required input, a failed or stale gate, a required human decision, or verified reframe completion
**Valid next commands:** /avo.watch

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

Extract a vertical (9:16) clip from an approved long-form master for Shorts repurposing.

**Skill:** [`agent-skills/avo-pipeline/references/reframe.md`](../../agent-skills/avo-pipeline/references/reframe.md)

---

## Usage

```
/avo.reframe
Provider: my-channel
rawDir: /path/to/footage
from: 2:30
to: 3:15
```

Optional: `crop: center | face-safe | custom` · `--preview`

---

## Role

Segment extract + crop/scale to 9:16. Output under `<rawDir>/edit/intermediates/` with immutable version naming. Hand off to `/avo.captions` or `/avo.shorts`.

---

## Instructions

1. Parse `Provider`, `rawDir`, `from`/`to` (required).
2. Require human-approved long-form master in `edit/masters/` or documented review export.
3. Follow [`reframe.md`](../../agent-skills/avo-pipeline/references/reframe.md) v1 ffmpeg/PIL workflow.
4. Preserve editorial meaning; label if crop changes viewer context.

---

## Example

```text
/avo.reframe
Provider: auto-lot
The footage is at D:/Dealer/walkthrough-march
from: 4:10
to: 4:55
crop: face-safe
```

## Shared timeline gateway

Runs the base pipeline with format-specific diagnosis and policy. It creates its own timeline context for derivatives and cannot bypass lineage, invalidation, Watch, transcript, or approval gates.
