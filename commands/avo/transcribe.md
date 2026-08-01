# /avo.transcribe Command

Transcribe only. No cut, no motion, no deliver.

**Skill:** [`docs/avo-pipeline/references/transcribe.md`](../../docs/avo-pipeline/references/transcribe.md)

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
