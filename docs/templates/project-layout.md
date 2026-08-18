# External video project layout (template)

Canonical `edit/` subtree for AVO per-video projects. Paths are relative to
`<rawDir>/edit/`. Media stays external; this file is agent-facing.

```
<rawDir>/
  <source files, untouched>
  EDITLOG.md                # PRESERVED audit — AVO digest + Human notes
  edit/
    project.md              # session memory (agent scratch; not the audit)
    timeline/               # PRESERVED — canonical editorial decisions
      cmap.json             # raw-based cut revisions
      bmap.json             # beats on exact approved CMap output
      tracks.json           # resolved audio/video layer assembly
      animation.json        # video animation strategy and references
      sync-map.json         # raw-based sync/resync decisions
      revisions/            # immutable per-artifact revision payloads
      events/               # immutable approvals/decisions
      pipeline-run.json     # persisted lifecycle and recovery
      migration.json        # migration/activation/rollback audit when applicable
      reconstruction-bundle.json
    edl.json                # GENERATED renderer compatibility projection
    takes_packed.md         # phrase-level transcript view
    transcripts/            # PRESERVED — initial + final JSON
    preview/                # proof MP4s for human watch (360p / 720p / pre-master)
    review/                 # human approval packages (one folder per checkpoint)
      edit-proof/
        review.json         # machine-readable candidate-bound evidence
        approval-gate.md
      motion-proof/
        review.json
        approval-gate.md
      pre-master/
        review.json
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
- Footage-root `EDITLOG.md` (AVO digest + Human notes; not a delete candidate)
- `transcripts/` (initial + final from master)
- `masters/` final export
- `timeline/` canonical snapshots, diffs, approvals, and dependency fingerprints
- compact `review/` evidence index and reconstruction manifest

Large previews and intermediates may be deleted post-approval. Canonical maps,
approval identity, evidence indexes, fingerprints, and projection metadata must
remain sufficient to reconstruct the edit without chat context or one-off code.
