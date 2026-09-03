# /avo.audio-qc Command

**Timeline integration:** Evidence

## Workflow guidance

**Workflow steps:** Validate audio qc prerequisites → Run audio qc → Verify and report the audio qc result
**Step state source:** current review.json and candidate-bound evidence
**Stopping conditions:** Missing required input, a failed or stale gate, a required human decision, or verified audio qc completion
**Valid next commands:** /avo.deliver

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

Loudness and delivery audio QC on the **approved master export**. Distinct from `/avo.sound` (mix/restoration).

**Skill:** [`agent-skills/avo-pipeline/references/audio-qc.md`](../../agent-skills/avo-pipeline/references/audio-qc.md)

---

## Usage

```
/avo.audio-qc
Provider: my-channel
rawDir: /path/to/footage
Footage: edit/masters/20260801-slug-master-v001.mp4
```

Optional: upload candidate path for post-encode true-peak re-check

---

## Role

Measure integrated loudness and true peak; document method and channel target; produce `<rawDir>/edit/review/audio-qc.md` before `/avo.deliver`.

---

## Instructions

1. Parse `Provider`, `rawDir`, optional `Footage:` (master path).
2. **Stop** if only rough cut exists — require approved master under `edit/masters/` or documented final path.
3. Load [`audio-qc.md`](../../agent-skills/avo-pipeline/references/audio-qc.md) and skill **`loudness-and-audio-delivery-qc`**.
4. Measure loudness + true peak; record standard/settings — no universal YouTube LUFS claim.
5. Write QC from [`docs/templates/review/audio-qc.md`](../../docs/templates/review/audio-qc.md).
6. Hand off to `/avo.deliver`.

---

## Example

```text
/avo.audio-qc
Provider: my-channel
The footage is at C:/Videos/my-edit
Footage: edit/masters/20260801-demo-master-v001.mp4
```

## Candidate-bound evidence

Evidence binds channel mapping, dialogue intelligibility, loudness, true peak, clipping, and residual sync results to the exact candidate SHA-256. Missing or ambiguous state blocks the applicable human gate.

## Shared timeline gateway

Runs shared candidate-bound checks and emits evidence with exact candidate/dependency hashes. Scoped evidence cannot satisfy a larger gate without required coverage.
