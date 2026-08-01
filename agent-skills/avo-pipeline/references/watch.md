# /avo.watch reference

Full **THE LOOP** via watch-skill. See [`docs/avo-workflow.md`](../../avo-workflow.md) §4.

## Steps

1. Select proof render (`edit/preview/*.mp4`).
2. watch-skill: inspect → defect list → confidence.
3. Agent applies fixes to owning stage tool.
4. Re-render proof; repeat until stable or user intervenes.
5. Write approval package:

```
edit/review/<checkpoint>/
  approval-gate.md
  (links to preview + analysis)
```

6. **Block** until user says approve.

## Checkpoint names

- `edit-proof` — after cut proof
- `motion-proof` — after motion proof
- `pre-master` — before 1080p/source promotion
