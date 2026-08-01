# /avo.trim reference

Edit-only path. See [`SKILL.md`](../../../SKILL.md) Hard Rules for cut correctness.

## Workflow

1. `transcribe_batch.py` → `pack_transcripts.py`
2. Strategy conversation → confirmed plan
3. `edl.json` → `render.py --preview`
4. Self-eval at cut boundaries (`timeline_view.py`)
5. `/avo.watch` or manual approval gate
6. Final cut export (no motion slots)

## Optional window

When `from`/`to` set, limit EDL and transcript analysis to that range only; do not imply content outside the window was reviewed.
