# /avo.trim reference

Edit-only path. See [`SKILL.md`](../../../SKILL.md) Hard Rules for cut correctness.
Cut workflow detail: [`cuts.md`](cuts.md).

## Workflow

1. `transcribe_batch.py` → `pack_transcripts.py`
2. Strategy conversation → confirmed plan (log cuts in **source time**)
3. `edl.json` with `blocked_source_ranges` + `anchor_in_source` on overlays
4. `python -m avo.edl_timeline verify edit/edl.json` → `write-docs`
5. `render.py --preview`
6. Transcript read + `/avo.watch` at cut boundaries (see [`cuts.md`](cuts.md))
7. Human approval gate — only after agent pre-review passes
8. Final cut export (no motion slots)

## Optional window

When `from`/`to` set, limit EDL and transcript analysis to that range only; do not imply content outside the window was reviewed.
