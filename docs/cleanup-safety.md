# Cleanup preservation and truthful learndown

Cleanup verifies both hashes and coverage. A correctly hashed bundle that omits a
current canonical local media dependency is not safe to execute. Current source
fingerprints, project configuration, the renderer EDL, authoring inputs and
delivery/approval documentation must survive. A changed or missing dependency
requires a fresh bundle; do not patch a bundle to bypass validation.

Projects can retain additional files or directories in `avo.project.json`:

```json
{
  "cleanup": {
    "preservePaths": ["edit/review", "edit/master", "edit/animations"]
  }
}
```

Entries must exist and be project-relative. Absolute paths, parent traversal,
the project root and links escaping the project are rejected. Retention is
additive: it never removes canonical protection. Inspect the resulting dry-run
before destructive execution. Private per-video choices belong in the external
project, not in reusable orchestrator code.

Execution writes `edit/cleanup/cleanup-result.json`: intent first, actual outcome
afterward. Only files verified absent after the attempted deletion contribute to
`deleted` and `freedBytes`. Failed deletions produce an incomplete result and
prevent session-scratch purge. An existing receipt prevents silent replacement;
review it before another execution.

Final wrap requires a completed receipt for the same project and master basename.
It never treats remaining candidates, an old draft, or a historical inventory
diff as proof of deletion. `--freed-bytes` is an optional consistency check,
not a way to invent a result. Draft wrap files remain as audit history after
finalization. Final learning does not authorize public publication or transfer
another video's approvals or music rights.
