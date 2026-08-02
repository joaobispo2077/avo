# /avo.animation-qc Command

Animation render QC after motion slots, before final composite. Wraps `animation-validation-and-render-qc`.

**Skill:** [`agent-skills/avo-pipeline/references/animation-qc.md`](../../agent-skills/avo-pipeline/references/animation-qc.md)

---

## Usage

```
/avo.animation-qc
Provider: my-channel
rawDir: /path/to/footage
```

Optional: composition path · `--preview` (720p slot proofs)

---

## Role

Validate determinism, accessibility, snapshot/render parity on motion outputs before composite master.

---

## Instructions

1. Parse `Provider`, `rawDir`.
2. Run after `/avo.motion` slot proofs approved; before final composite deliver.
3. Load [`animation-qc.md`](../../agent-skills/avo-pipeline/references/animation-qc.md) and **`animation-validation-and-render-qc`**.
