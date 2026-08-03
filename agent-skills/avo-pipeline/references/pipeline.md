# /avo.pipeline reference

Load [`arguments.md`](arguments.md) first.

## Stages executed

| # | Stage | Tool | Inputs | Outputs |
| - | ----- | ---- | ------ | ------- |
| 0 | Plan | Spec Kit (optional) | scope | spec/plan |
| 0b | Session start | `session.py start` | rawDir | `pre.json` |
| 1 | Transcribe | faster-whisper | raw file(s) | **initial transcript** |
| 2 | Edit | render helpers | transcript, EDL | cut proofs |
| 3 | Verify | watch-skill | proof render | agent QC + human gate |
| 4 | Motion | HyperFrames | approved cut | motion proof + human gate |
| 5 | Render | `avo.render --youtube-4k` | approved pre-master | **final master** + **final transcript** (auto) |
| 6 | Deliver | QC + manifest | master + final transcript | delivery manifest |
| 7 | Learndown + cleanup | rimraf | project tree | preserved set only |
## Asset manifest

Write to `avo.project.json`:

```json
{
  "provider": "<provider>",
  "rawDir": "<rawDir>",
  "assets": {
    "footage": "<Footage>",
    "sfx": "<SFX>",
    "inserts": "<B-roll>",
    "music": "<Music>",
    "logos": "<Logo>"
  }
}
```

## Flags

- `--skip-motion`: stop after approved edit master
- `--preview`: hold 360p/720p until user promotes
