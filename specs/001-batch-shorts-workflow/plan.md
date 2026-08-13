# Implementation Plan: Batch Shorts Workflow

**Version:** 1.2
**Updated:** 2026-08-13
**Spec:** [spec.md](spec.md)

## System status

US1–US4 runtime and Phase 8–9 audit fixes are implemented. Migration gates T072 and script retirement remain operator-gated.

## Preview tier invalidation (v1.2)

- Each proof build records `renderProfile` on status items: `{ preview, width, height }`.
- `dirty_items(..., preview=flag)` compares stored profile to the target profile for the requested build.
- Preview proofs at 640×360 automatically dirty when a full-resolution build is requested.
- CLI `qc` still validates against plan `output`, so preview proofs fail geometry until rebuilt.

## Provider tokens

- [shorts_provider.py](../../src/avo/shorts_provider.py) loads `providers/<slug>/brand/palette.json`.
- Resolved plans store `providerTokens` + fingerprint; builds pass tokens into HyperFrames.
- Missing palette adds a non-fatal plan warning.

## QC pipeline

- `analyze_video_metrics()` — FFmpeg blackdetect, freezedetect, ebur128.
- CLI `qc` fills per-item findings and `batchQcSummary`.
- Geometry checks use plan `output`.

## Visual evidence

- Contact sheets generated after HyperFrames strict check when snapshots exist.
- Stored as immutable `contact-sheet` artifacts.

## Schema refinements enforced

- `punchSelection: last-content-word`
- `selectionRule: lowest-visual-interest | ordered`
- `cropMode: cover | contain`
- `visualInterestScore` on candidates (for allocation rule)

## Master promotion

Proof at target resolution is the deliverable candidate. `promote` copies proof to master and generates final-file transcript sidecars.

## Test matrix (Phase 9)

| Area | Tests |
|------|-------|
| Preview invalidation | `test_shorts_batch_integration.py` |
| QC CLI + batchQcSummary | `test_shorts_batch_integration.py` |
| Promote CLI | `test_shorts_batch_integration.py` |
| Provider tokens | `test_shorts_provider.py` |
| Selection rule / warnings | `test_shorts_plan.py` |
| QC metrics wiring | `test_shorts_qc.py` |

## Open migration gates

- T072 real Switch batch — see [t072-switch-migration-runbook.md](t072-switch-migration-runbook.md)
- T075–T076 script retirement after Watch approval
- T078 validation record in [tasks.md](tasks.md)
- T079 constitution recheck after T072
