# External video project layout (template)

Canonical `edit/` subtree for AVO per-video projects. Paths are relative to
`<rawDir>/edit/`. Media stays external; this file is agent-facing.

```
<rawDir>/
  <source files, untouched>
  edit/
    project.md              # session memory
    edl.json                # cut decisions
    takes_packed.md         # phrase-level transcript view
    transcripts/            # PRESERVED — initial + final JSON
    preview/                # proof MP4s for human watch (360p / 720p / pre-master)
    review/                 # human approval packages (one folder per checkpoint)
      edit-proof/
        approval-gate.md
      motion-proof/
        approval-gate.md
      pre-master/
        approval-gate.md
    verify/                 # debug frames, QC JSON (optional)
    animations/             # motion slots (optional)
    clips_graded/           # intermediates (deleted on cleanup)
    masters/                # PRESERVED — final master after approval
```

## Human approval gate

After watch-skill LOOP + agent transcription analysis at each checkpoint, the
agent writes/updates `review/<checkpoint>/approval-gate.md` and **waits** for
explicit user approval before promoting resolution or advancing.

See [`../../specs/active/avo-approval-gates-ux/spec.md`](../../specs/active/avo-approval-gates-ux/spec.md)
and [`../review/approval-gate-manifest.md`](review/approval-gate-manifest.md).

## Preserved after cleanup

- Raw source files (outside `edit/` or in `raw/`)
- `transcripts/` (initial + final from master)
- `masters/` final export

Everything else under `edit/` may be deleted post-approval per learndown rules.
