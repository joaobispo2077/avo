# Composite validation — boil overlay

Validate alpha boil clips through the existing orchestrator — **no render.py changes**.

## EDL shape

```json
{
  "overlays": [
    {
      "file": "edit/animations/slot_boil-callout/render.webm",
      "start_in_output": 12.5,
      "duration": 2.5,
      "motion_brief_id": "boil-callout",
      "anchor_in_source": 45.0
    }
  ]
}
```

## FFmpeg graph (render.py)

For each overlay input:

1. `format=yuva420p`
2. `trim=duration=<edl.duration>`
3. `setpts=PTS-STARTPTS+<start_in_output>/TB`
4. `overlay=enable='between(t,start,end)'`

Captions filter appended **after** all overlays when burn-in enabled.

## Manual QC

1. Render boil starter to WebM at draft quality
2. Place in slot folder; register EDL entry
3. Run final composite at 720p proof
4. Review alpha edges on dark and light base footage
5. Confirm overlay disappears at EDL end (trim prevents bleed)

## Automated

See `tests/test_boil_overlay_integration.py` — graph shape + captions-last.
