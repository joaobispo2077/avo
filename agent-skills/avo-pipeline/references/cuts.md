# Cut process reference

Cuts must never be applied from **uncut source timestamps** after an earlier
range removal — every later cut and overlay must be **re-mapped**.

## Source-first rule

1. Log user notes in **source time** on the main camera file (`blocked_source_ranges`).
2. When the user reports a problem on a **proof render**, convert with  
   `python -m avo.edl_timeline map <edl.json> <seconds> --from output`  
   before editing ranges.
3. Split `ranges` at `final_cut_start` / `final_cut_end` (word-boundary pad).
4. Store overlay/SFX timing as **`anchor_in_source`** (canonical).
5. Derive `start_in_output` via `python -m avo.edl_timeline verify <edl.json>`  
   or `remap_timed_items()` — never guess B-time after a cut change.

## Required artifacts (before human review)

| File | Purpose |
| --- | --- |
| `edit/cut-map.md` | Source↔B-time table for every removed span + kept ranges |
| `edit/animations/beat-map.md` | Overlay/SFX B-time QC table (from anchors) |
| `edit/edl.json` | `blocked_source_ranges` + `anchor_in_source` on timed items |

Generate docs:

```bash
python -m avo.edl_timeline write-docs edit/edl.json
```

## Agent pre-human gate (blocking)

Before writing `approval-gate.md` or asking the creator to watch:

1. **`edl_timeline verify`** — anchors match `start_in_output`.
2. **Transcript read** — cut edges land on pauses/word gaps; privacy spans do not
   remove requested speech; note source times in the review package.
3. **`/avo.watch` (watch-skill)** on the proof with `--timestamps` at:
   - every range join (±2s),
   - every `blocked_source_ranges` mapped B-window,
   - every overlay `start_in_output`.
4. Fix → re-render → repeat until watch-skill + transcript checks pass.

High watch-skill confidence **does not** skip this gate and **does not** replace
human approval (workflow §4b).

## Common failure (this project)

Applying privacy cut at uncut **10:30–10:46** after removing **08:05–08:28**
cut the wrong speech (Xbox line) and left the wife segment at **B ~09:51–10:07**.
Always remap privacy cuts from the **current** proof timeline.
