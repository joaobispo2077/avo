# /avo.transcribe Command

**Timeline integration:** Evidence

## Workflow guidance

**Workflow steps:** Validate transcribe prerequisites → Run transcribe → Verify and report the transcribe result
**Step state source:** current review.json and candidate-bound evidence
**Stopping conditions:** Missing required input, a failed or stale gate, a required human decision, or verified transcribe completion
**Valid next commands:** /avo.trim or /avo.pipeline

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

Transcribe only. No cut, no motion, no deliver.

**Skill:** [`agent-skills/avo-pipeline/references/transcribe.md`](../../agent-skills/avo-pipeline/references/transcribe.md)

---

## Usage

```
/avo.transcribe
Provider: my-channel
rawDir: /path/to/footage
Footage: /path/to/main.mp4
```

Optional: `--lang pt` (override provider default) · `--force` (re-transcribe even if cached)

---

## Role

Stage 1 only: faster-whisper word-level JSON + optional `takes_packed.md`. Stops before edit strategy.

---

## Instructions

1. Parse `Provider`, `rawDir`, `Footage` (required).
2. Verify multilingual model prepared (`prepare_transcription.py`); fail fast with setup hint if missing.
3. Run `transcribe_batch.py` → cache under `<rawDir>/edit/transcripts/`.
4. Run `pack_transcripts.py` → `edit/takes_packed.md`.
5. Report word count, duration, language detected. **Do not** propose cuts unless user asks.

---

## Example

```text
/avo.transcribe
Provider: physio-edu
rawDir: H:/footage/exercise-demo
Footage: H:/footage/exercise-demo/raw/take-a.mp4
--lang en
```

## Candidate-bound evidence

Evidence binds transcript hash and semantic name, term, cut-edge, and meaning findings to the exact candidate SHA-256 and dependency snapshot. Missing or ambiguous state blocks the applicable human gate.

## Shared timeline gateway

Runs shared candidate-bound checks and emits evidence with exact candidate/dependency hashes. Scoped evidence cannot satisfy a larger gate without required coverage.
