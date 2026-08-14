# Audit Resolutions: Batch Shorts Workflow

**Date:** 2026-08-13
**Source audit:** `/audit` on `001-batch-shorts-workflow` (2026-08-12)
**Status:** Major/minor runtime gaps addressed; migration gates unchanged

## Revision History

| Version | Date | Change | Reason |
|---------|------|--------|--------|
| 1.2 | 2026-08-13 | Preview `renderProfile` tracking + dirty invalidation | Preview builds no longer block full-res rebuild |
| 1.1 | 2026-08-13 | Close audit majors #1–#6 and minors #9–#11 in runtime + docs | Spec/code drift after US1–US4 implementation |
| 1.0 | 2026-08-10 | Initial feature specification | Batch Shorts workflow MVP |

## Resolved In Runtime (2026-08-13)

| Audit ID | Resolution |
|----------|------------|
| #1 Provider tokens | `shorts_provider.py` loads provider palette at resolve; plan stores `providerTokens`; build passes tokens into HyperFrames composition |
| #2 QC black/freeze/loudness | `shorts_media.analyze_video_metrics()` + `qc_proof_artifact()` wired through CLI `qc` |
| #3 Contact sheets | Generated after HyperFrames strict check; stored as `contact-sheet` artifacts |
| #4 CLI vs agent flags | `commands/avo/shorts.md` clarifies agent-only vs executable flags; `build --preview` added |
| #5 Master = proof copy | Documented intentional: proof already renders target delivery geometry/audio; promotion copies immutable proof |
| #6 Schema refinements | `punchSelection`, `selectionRule`, `cropMode` now applied in captions/plan/media |
| #9 QC geometry | `evaluate_item()` uses plan `output` width/height |
| #10 Status bootstrap | `_new_status()` reflects real `planApproval` state |
| #11 batchQcSummary | Populated by CLI `qc` with pass/fail counts |

## Still Open (Intentional)

| Audit ID | Status | Gate |
|----------|--------|------|
| #7 Real-footage validation | External | Owned by the footage project; no private migration state is tracked in AVO |
| #8 Script retirement | Complete | Generic `/avo.shorts` coverage replaces repository-specific repair scripts |
| T078 validation record | Pending | Run full suite and record commands/results in `tasks.md` |
| T079 repository-purity recheck | Complete | Generic runtime retained; private automation removed |

## Design Decisions

### Master promotion copies proof
Proof render already uses plan output profile (1080×1920, 48 kHz dialogue, CFR). Re-encoding at promotion would add cost without changing editorial parameters. Promotion remains a checksum-preserving copy plus fresh final-file transcripts.

### `--from-master` and `--skip-motion`
Agent orchestration hints only. Extraction intent belongs in `shorts.request.json` (`source.masterPath`, candidate ranges). Motion skipping is out of scope for v1 because captions and layout are HyperFrames-owned.

### `--preview`
Executable on `python -m avo.shorts build <plan> --stage proof --preview` (640×360). Agent may still recommend cheap proof review before full-resolution rebuild.

### `lowest-visual-interest` allocation
Selects candidates with lowest optional `visualInterestScore` (default 50). Does not infer scores from footage; agent must supply scores when using this rule.

### Preview render profile (v1.2)
Each proof build stores `renderProfile` on status items. Requesting a full-resolution build after preview automatically dirties all items with `render-profile-changed`.
