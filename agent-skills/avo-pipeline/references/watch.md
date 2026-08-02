# /avo.watch reference

Full **THE LOOP** via watch-skill. See [`docs/avo-workflow.md`](../../avo-workflow.md) §4.

**Blocking:** Do not open the human approval gate until watch-skill **and** transcript
analysis both pass. Cut/motion proofs also require [`cuts.md`](cuts.md) pre-review.

## Steps

1. Select proof render (`edit/preview/*.mp4`).
2. Run `python -m avo.edl_timeline verify edit/edl.json` when EDL changed.
3. **Transcript read:** confirm cut edges, privacy spans, names/terms; record source
   times in the review package.
4. watch-skill: inspect → defect list → confidence. Pass `--timestamps` for every
   range join, blocked-range B-window, and overlay `start_in_output`.
5. Agent applies fixes to owning stage tool.
6. Re-render proof; repeat until stable or user intervenes.
7. Write approval package:

```
edit/review/<checkpoint>/
  approval-gate.md
  (links to preview + analysis)
```

6. **Block** until user says approve.

## Agent pre-human gate (required)

Complete **before** step 7 above and before asking the creator to watch:

| Check | Tool |
| --- | --- |
| Source↔B-time consistency | `python -m avo.edl_timeline verify` |
| Cut/privacy correctness | Transcript JSON + [`cuts.md`](cuts.md) |
| Visual QC | watch-skill with boundary/overlay timestamps |

See [`cuts.md`](cuts.md) for the full cut-map / beat-map requirements.

## Checkpoint names

- `edit-proof` — after cut proof
- `motion-proof` — after motion proof
- `pre-master` — before 1080p/source promotion
