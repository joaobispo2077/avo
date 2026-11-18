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

## Available speech-completeness evidence

Cutting analysis now returns compact `coverage.speech` review links and retains
strict `speechCoverage` beside its source-analysis words and acoustic evidence.
Inspect those bound facts before asserting a missing take or an exact spoken
trigger. Missing source/routing/Sync, model provenance or measured coverage stays
unavailable; acoustic activity is possible speech and may be a false positive.
Partial observation and unreliable word timing remain visible for review.

Unresolved source intervals protect retake rejection through the existing cutting
policy. The report does not replace a transcript or grant cut approval. Coverage
inspection starts no decode, ASR or alignment and does not bypass this stage's
cache rule. `avo preparation coverage --project <absolute manifest> --request
<absolute request> --json` reinspects an exact retained analysis using metadata
only. Explicit `preparation recover` freezes selected source intervals, language
and enabled recovery options, consumes a durable attempt before local inference
and preserves the original/recovered alternatives for review. Defaults are one
attempt per interval, 30 seconds per interval and 120 seconds total; oversized
scopes are rejected without clipping. Missing alignment preserves recovered text
without exact word anchors or safe-cut certification. Restart reuses evidence;
interrupted attempts do not run again automatically. Evidence selection and cut
approval remain separate gates. See [source speech coverage](../../../docs/speech-coverage.md).
