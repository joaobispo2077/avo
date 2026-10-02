# /avo.trim reference

## Step/state mapping

**Durable state:** pipeline-run.json plus the current canonical timeline revision

**Workflow steps:** Validate trim prerequisites → Run trim → Verify and report the trim result

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing required input, a failed or stale gate, a required human decision, or verified trim completion

**Valid next commands:** /avo.watch

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

Breathing remains off unless requested. For approved breath duration changes,
load [breathing guidelines](guidelines-breathing.md). Emit raw-source CMap cut
proposals, preserve cadence and word guards, and remap dependent cues. Never
delete time solely from the dialogue track. Attenuation without a duration
change belongs to `/avo.sound`.

When `from`/`to` set, limit EDL and transcript analysis to that range only; do not imply content outside the window was reviewed.
