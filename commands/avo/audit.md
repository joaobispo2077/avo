# /avo.audit Command

**Timeline integration:** Evidence

## Workflow guidance

**Workflow steps:** Validate audit prerequisites → Run audit → Verify and report the audit result
**Step state source:** current review.json and candidate-bound evidence
**Stopping conditions:** Missing required input, a failed or stale gate, a required human decision, or verified audit completion
**Valid next commands:** /avo.watch or /avo.deliver

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

Scoped quality check on a cut, transcript, or time slice.

**Skill:** [`agent-skills/avo-pipeline/references/audit.md`](../../agent-skills/avo-pipeline/references/audit.md)

---

## Usage

```
/avo.audit
Provider: my-channel
rawDir: /path/to/footage
from: 9:30
to: 9:35
--only-transcription
```

Flags (one or both):

- `--only-transcription` — word timing, filler tags, caption alignment
- `--only-video` — cut continuity, grade, overlays, sync

Omit both flags for a balanced audit of the window.

---

## Role

Fast QC without running the full watch-skill LOOP. Use before asking the user to approve a gate.

---

## Instructions

1. Parse window (`from`/`to`) or audit entire latest proof in `edit/preview/`.
2. **`--only-transcription`:** Compare `takes_packed.md` / transcript JSON to master SRT; flag word-boundary violations, missing terms, drift vs EDL.
3. **`--only-video`:** Run `timeline_view.py` at cut boundaries ±1.5s; check pops, overlay/caption occlusion, grade consistency.
4. Output a short pass/fail report with timestamps and fix suggestions.
5. Do **not** auto-promote resolution or skip human approval.

---

## Example

```text
/avo.audit
rawDir: /videos/review
from: 9:30
to: 9:35
--only-video
```

## Shared evidence runner

`/avo.audit` runs selected checks through the shared orchestrator and writes
candidate-bound scoped evidence. A partial audit cannot satisfy a checkpoint
unless the declarative gate matrix confirms all required kinds and coverage.

## Shared timeline gateway

Runs shared candidate-bound checks and emits evidence with exact candidate/dependency hashes. Scoped evidence cannot satisfy a larger gate without required coverage.
