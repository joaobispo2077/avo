# /avo.trim Command

Transcribe and cut only. Skip motion unless the user asks to continue.

**Skill:** [`docs/avo-pipeline/references/trim.md`](../../docs/avo-pipeline/references/trim.md)

---

## Usage

```
/avo.trim
Provider: my-channel
rawDir: /path/to/footage
Footage: /path/to/main.mp4
```

Optional: `from: 9:30` `to: 12:00` (limit working region) · `--preview`

---

## Role

Run stages 1–2 (+ deliver cut master): transcribe → edit/caption → watch-skill LOOP → human approval → export edit master. No HyperFrames pass by default.

---

## Instructions

1. Parse `Provider`, `rawDir`, `Footage` (required).
2. Follow [`SKILL.md`](../../SKILL.md) process through edit proof.
3. Default to **360p preview** until user approves promotion.
4. After approval, render cut master to `edit/masters/` or `edit/final.mp4` per project convention.
5. Do **not** spawn motion sub-agents unless user explicitly requests `/avo.motion` next.

---

## Example

```text
/avo.trim
Provider: my-channel
rawDir: /videos/product-review
Footage: /videos/product-review/raw/take-a.mp4
```
