# /avo.pipeline reference

Load [`arguments.md`](arguments.md) first.

## Stages executed

| # | Stage | Tool |
| - | ----- | ---- |
| 0 | Plan | Spec Kit (optional) |
| 1 | Transcribe | faster-whisper |
| 2 | Edit | video-use + render helpers |
| 3 | Verify | watch-skill |
| 4 | Motion | HyperFrames |
| 5 | Render | local render |
| 6 | Deliver | master + final transcript |
| 7 | Cleanup | rimraf + learndown |

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
