# Feature Specification: Batch Shorts Workflow

**Version:** 1.2
**Created:** 2026-08-10
**Updated:** 2026-08-13
**Status:** Draft — runtime complete through US4 + Phase 9; migration gates open

## Revision History

| Version | Date | Description | Reason |
|---------|------|-------------|--------|
| 1.2 | 2026-08-13 | Preview render-profile invalidation + Phase 9 tests/docs | Close preview→full-res rebuild gap |
| 1.1 | 2026-08-13 | Audit resolution pass | Provider tokens, QC depth, schema refinements |
| 1.0 | 2026-08-10 | Initial specification | Reusable ten-Short batch workflow |

## Scope

One approved master and transcript produce a reviewable, parameter-driven batch of vertical Shorts without project-specific scripts. HyperFrames is internal.

## Key requirements (current)

- **FR-011**: Provider design tokens resolved from provider palette at plan time and passed to proof builds.
- **FR-016**: Contact-sheet visual evidence when HyperFrames snapshots exist.
- **FR-017**: CLI `qc` includes probe, captions, Watch insertion review, and supporting black/freeze/loudness metrics.
- **FR-018**: Master promotion copies approved proof at target delivery geometry (no separate re-encode in v1).
- **FR-022**: Script retirement blocked until T072 Watch approval.

## Preview workflow

- `build --stage proof --preview` renders 640×360 proofs.
- Full-resolution rebuild is automatic: status `renderProfile` mismatch marks items dirty.
- Promotion requires QC-passed full-resolution proofs.

## CLI surface

`validate`, `resolve`, `build --stage proof|master`, `build --preview`, `qc`, `status`, `promote`.

Agent-only: `--from-master`, `--skip-motion` (expressed in `shorts.request.json`).

## References

- [audit-resolutions.md](audit-resolutions.md)
- [quickstart.md](quickstart.md)
- [t072-switch-migration-runbook.md](t072-switch-migration-runbook.md)
