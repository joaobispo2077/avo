# /avo.reframe Command

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
