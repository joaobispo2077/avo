# /avo.chapters Command

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
