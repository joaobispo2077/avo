# /avo.transcribe reference

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
