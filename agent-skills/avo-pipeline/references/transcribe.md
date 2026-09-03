# /avo.transcribe reference

## Step/state mapping

**Durable state:** current review.json and candidate-bound evidence

**Workflow steps:** Validate transcribe prerequisites → Run transcribe → Verify and report the transcribe result

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing required input, a failed or stale gate, a required human decision, or verified transcribe completion

**Valid next commands:** /avo.trim or /avo.pipeline

Stage 1 only. Owning tool: video-use + faster-whisper (`avo.config.json` → `transcribe`).

## Workflow

1. Verify model dir (`prepare_transcription.py --model small` or provider default)
2. `transcribe_batch.py` on `Footage` path(s)
3. Cache JSON: `<rawDir>/edit/transcripts/<basename>.json`
4. `pack_transcripts.py` → `edit/takes_packed.md`

## Cache rule

Do **not** re-transcribe unless source file changed or `--force`. Hard Rule #9 in [`SKILL.md`](../../../SKILL.md).

## Language

- Provider default from `avo.provider.json` / setup `--lang`
- Override with `--lang CODE` on command line

## Stops before

- EDL / cut strategy
- watch-skill
- Motion slots

Next step is usually strategy conversation or `/avo.trim`.
