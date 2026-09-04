# Implementation Plan: Generic Guided AVO Workflows

**Branch**: `feature/avo-mcp` (preserved by repository policy) | **Date**: 2026-09-01 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/005-generic-guided-workflows/spec.md`

## Summary

Generalize the current Shorts, Watch, delivery-QC, and AVO-agent prompt changes without retaining one provider's paths, hardware, language, topic, or output assumptions. The implementation stays in AVO's existing Python CLI and adapter structure: add a pure canonical Shorts path resolver and ordered lineage normalization, resolve Watch policy through documented global/provider/registry/project/invocation precedence, feed canonical materialization lineage plus a declared delivery profile into deterministic fidelity QC, and add one shared end-of-response step-status contract to all AVO-owned skills and `/avo.*` prompts.

New behavior is opt-in where it is not universally safe: invocation-only choices use flags, persistent choices use validated configuration, and effective values plus their source are recorded before expensive work. Legacy single-range Shorts plans remain readable through explicit normalization; no existing files are moved automatically.

## Technical Context

**Language/Version**: Python 3.10+; Markdown command/skill prompts; JSON Schema draft 2020-12

**Primary Dependencies**: Python standard library, `jsonschema`, FFmpeg/FFprobe adapters, Watch Skill executable, existing AVO canonical timeline services

**Storage**: Project-owned JSON/Markdown/media artifacts beneath `<rawDir>/edit/`; repository JSON configuration and schemas

**Testing**: `pytest` unit/contract/integration tests, Ruff, Prettier, existing `npm run quality` gates

**Target Platform**: Windows, Linux, and macOS local CLI environments; paths resolved with `pathlib`

**Project Type**: Single deployable local-first Python CLI/orchestrator with agent prompt packages

**Performance Goals**: Resolve paths, policy, lineage, and prompt state before media work begins; avoid duplicate media hashing or rendering when immutable hashes are already available; preserve existing bounded Watch retries

**Constraints**: Preserve the dirty worktree and current branch; no project-specific helpers or private paths; no network dependency during render/review contract resolution; fail closed at pre-master/delivery when lineage is missing or stale; no automatic migration or overwrite of immutable artifacts

**Scale/Scope**: Four reusable runtime contracts, 51 `/avo.*` command wrappers, the AVO gateway/top-level skills and routed references, existing Shorts schemas/CLI/tests, Watch/review adapters, canonical timeline materialization, QC registry, and user documentation

## Constitution Check

*GATE: Passed before Phase 0 research and re-checked after Phase 1 design.*

- **Editorial truth and viewer promise — PASS**: ordered source segments retain exact source order, evidence, rationale, and hashes. Prompt guidance and fidelity checks cannot claim approval from chat state or filename labels.
- **Format diagnosis before style — PASS**: Watch context accepts the declared format diagnosis and acceptance criteria; defaults remain topic-, language-, and format-neutral. The feature introduces no pacing, graphics, music, B-roll, or effects choices.
- **Audio/visual/accessibility quality — PASS**: segment assembly preserves synchronized picture/dialogue mapping and forces caption phrase boundaries at edit seams. Fidelity evaluates declared geometry, frame rate, duration, and encoding policy rather than a universal bitrate.
- **Rights/disclosure/safety/privacy — PASS**: source lineage, insertion sources, rights references, approvals, and risk windows remain in delivery/source records. Missing evidence blocks release rather than being inferred.
- **Versioning/review/QC — PASS**: request/plan/proof/master versions remain immutable; legacy artifacts are read without moving; Watch and deterministic QC stay before human approval; masters require candidate-bound pre-master/delivery evidence.

Post-design re-check: the contracts in `contracts/` preserve all five gates. No constitution exception or complexity waiver is required.

## Project Structure

### Documentation (this feature)

```text
specs/005-generic-guided-workflows/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── avo-step-status.md
│   ├── delivery-fidelity.md
│   ├── shorts-batch-and-lineage.md
│   └── watch-policy.md
└── tasks.md                  # generated later by /speckit.tasks
```

### Source Code (repository root)

```text
src/avo/
├── shorts.py                         # CLI flags; all stages consume resolver
├── shorts_paths.py                   # new pure canonical path resolver
├── shorts_plan.py                    # legacy normalization + ordered plan lineage
├── shorts_media.py                   # ordered multi-segment preparation/assembly
├── shorts_captions.py                # per-segment remap; seam-safe phrase breaks
├── shorts_delivery.py                # manifests/logs/reconstruction preservation
├── delivery_fidelity.py              # pure resolved policy + evaluation
├── video_context.py                  # persistent config merge
├── cli.py                            # review invocation overrides + context handoff
├── adapters/
│   ├── understand/
│   │   ├── watch_policy.py           # new pure resolution/prompt policy
│   │   └── watch_skill.py            # subprocess adapter only
│   └── qc/
│       ├── registry.py               # checkpoint registration and disposition
│       └── source_fidelity.py        # refactor current diff to consume policy/lineage
└── timeline/
    ├── materialize.py                # candidate-bound picture ancestry/profile
    ├── picture_lineage.py            # actual render-contributor graph
    └── review_runner.py              # forwards Watch/fidelity context into evidence

schemas/
├── avo.project.schema.json
├── avo.shorts-batch.schema.json
├── avo.shorts-plan.schema.json
├── avo.shorts-status.schema.json
├── avo.review-evidence.schema.json
└── avo.materialization.schema.json

providers/
└── avo.provider.schema.json

agent-skills/
├── avo/SKILL.md
└── avo-pipeline/
    ├── SKILL.md
    └── references/
        ├── arguments.md
        ├── step-status.md            # new shared response contract
        └── *.md                      # workflow steps/gates/next commands

commands/avo/*.md                     # all wrappers declare steps + shared contract
docs/
├── avo-agent-step-status.md
├── shorts-batch-paths-and-lineage.md
├── watch-review-policy.md
└── delivery-fidelity.md

tests/
├── test_avo_commands.py
├── test_avo_step_status_contract.py
├── test_timeline_command_runtime.py
├── test_shorts_paths.py
├── test_shorts_contract.py
├── test_shorts_plan.py
├── test_shorts_media.py
├── test_shorts_captions.py
├── test_shorts_batch_integration.py
├── test_shorts_delivery.py
├── test_watch_policy.py
├── test_watch_adapter.py
├── test_source_fidelity_qc.py
├── test_review_runner.py
└── test_delivery_service.py
```

**Structure Decision**: Keep AVO's current pragmatic single-project organization. Pure policy/path modules are introduced only where several callers need one deterministic contract; subprocess, filesystem, and FFmpeg behavior stays at existing adapter boundaries. No Clean Architecture tree, repository abstraction, or project-specific script is added.

## Implementation Design

### 1. Shared settings resolution

- Add one merge helper that resolves an object field-by-field and returns both `values` and `sources`.
- Persistent Watch settings resolve `global → provider routingOverrides → registry defaults → project`; explicit CLI values resolve last. Invalid values fail before Watch indexing.
- Do not add a Watch-disable flag: exact-candidate Watch remains a mandatory review gate where current workflow rules require it.
- Record the effective Watch policy in Watch evidence; record canonical Shorts roots in plan/status/delivery manifests.

### 2. Canonical Shorts paths and lineage

- Add immutable `ShortsBatchPaths` returned from `<rawDir> + batchId` or a validated project-owned `--batch-dir` override.
- Persist the resolved root in an atomic project-owned Shorts index so reconstruction and cleanup can discover validated nested overrides without broad filesystem guessing.
- Route validate/resolve/build/qc/status/promote, reconstruction, and cleanup preservation through this resolver.
- Introduce request/plan contract version `1.1`. New requests give the primary source a stable `sourceId` and use per-candidate ordered `sourceSegments[]`; resolver output contains source fingerprints and an output/source time map for every segment.
- Normalize a valid v1.0 `source.masterPath + sourceRange` into one in-memory segment without changing meaning. New writes use v1.1; legacy files remain in place.
- Prepare each segment in declared order, concatenate deterministic picture/dialogue assets, and prevent one caption phrase from crossing a segment boundary.

### 3. Configurable Watch boundary

- Move policy resolution and prompt construction into pure `watch_policy.py`; keep executable discovery and subprocess execution in `watch_skill.py`.
- Build prompts from checkpoint, declared format/language, acceptance criteria, risk windows, transcript reference, and project facts. Remove hardcoded topic, provider, language, format, path, model, and device assumptions.
- Preserve tolerant UTF-8 capture and JSON extraction, but accept only the last schema-valid structured result for the requested candidate. Refusal, malformed output, insufficient coverage, and uncertainty remain separate fail-closed dispositions.

### 4. Lineage-fed delivery fidelity

- Route assembly rendering through an immutable materialization and extend its record with a resolved output profile and ordered picture-carrying ancestry derived from actual CMap ranges, compiled overlay roles, source fingerprints, and renderer inputs.
- Require `--materialization` for `pre-master` and `deliver` review. Raw candidate paths plus ad hoc hashes are insufficient at these checkpoints.
- Refactor source-fidelity QC to compare the candidate with the declared profile and each picture ancestor after declared transformations. Bitrate thresholds apply only when the chosen profile declares one.
- Map a candidate/profile violation to review failure; map missing, stale, or contradictory lineage/profile data to a blocked prerequisite with exact artifact references.

### 5. Guided AVO agent responses

- Add one canonical prompt reference defining an end-of-response four-line block: workflow, current step/status, next step, and next expected update.
- Every AVO command wrapper declares its ordered workflow steps and points to the shared response contract; routed references define gates, stops, durable-state mapping, and valid next commands.
- Extend static command tests so a missing step declaration/contract/next-command rule fails CI. Runtime status is derived from durable timeline/Shorts/project state, never invented from conversation history.

### 6. Existing diff disposition

- Keep and regression-test reusable behavior already present in the worktree: `camera_source_keys` gain handling, canonical locator/path fallback, cross-platform grade scratch paths, the loudness-preset hook, caption timing clamping, final transcript placement, Shorts preservation/reconstruction, delivered-QC state retention, tolerant Watch UTF-8 capture, and structured-result parsing.
- Refactor the current Shorts path, Watch policy, and source-fidelity diffs through the contracts above rather than discarding their generic improvements.
- Remove provider/topic/hardware/path assumptions from Watch. Delete `ffmpeg_filter_file_arg()` only if the implementation audit confirms it remains unreachable. Keep `-shortest` only with regression tests proving requested duration and audio/video synchronization.
- Keep footage-project fixtures and one-video assertions under `tests/projects/` or external footage projects; core tests must use neutral fixtures and paths.

## Migration and Rollout

1. Lock the reusable parts of the current dirty diff with neutral regression tests; do not overwrite unrelated user changes.
2. Land shared pure contracts and compatibility readers.
3. Add schemas/config resolution and make effective settings inspectable.
4. Route Shorts stages through canonical paths, then add v1.1 multi-segment output.
5. Refactor Watch without changing mandatory review gates.
6. Add materialization lineage/profile and then enable mandatory fidelity at pre-master/deliver.
7. Update all AVO prompt packages and docs; enable static enforcement last in the same change so no partially migrated wrapper ships.
8. Keep v1.0 Shorts and legacy `--delivery-dir` readable for one documented compatibility window. Only v1.0 plans may use a legacy split delivery path; v1.1 rejects it and directs users to `--batch-dir` at resolution time.

## Complexity Tracking

No constitution violations or additional architectural layers require justification.
