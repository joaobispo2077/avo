# /avo.animation-qc Command

**Timeline integration:** Evidence

## Workflow guidance

**Workflow steps:** Validate animation qc prerequisites → Run animation qc → Verify and report the animation qc result
**Step state source:** current review.json and candidate-bound evidence
**Stopping conditions:** Missing required input, a failed or stale gate, a required human decision, or verified animation qc completion
**Valid next commands:** /avo.motion or /avo.deliver

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

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

## Candidate-bound evidence

Evidence binds overlay lifecycle, face/caption/evidence avoidance, readability, flashing safety, and render parity to the exact candidate SHA-256. Missing or ambiguous state blocks the applicable human gate.

## Shared timeline gateway

Runs shared candidate-bound checks and emits evidence with exact candidate/dependency hashes. Scoped evidence cannot satisfy a larger gate without required coverage.
