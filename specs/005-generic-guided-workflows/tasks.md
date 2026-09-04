# Tasks: Generic Guided AVO Workflows

**Input**: Design documents from `specs/005-generic-guided-workflows/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`

**Tests**: Required. The specification defines independent tests for every user story and repository policy requires TDD plus `npm run quality` for orchestrator changes.

**Organization**: Tasks are grouped by user story so each capability can be implemented and verified as an independent increment. Preserve the checked-out branch and all unrelated user changes in the dirty worktree.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel because it uses different files and has no incomplete dependency.
- **[Story]**: Maps the task to the corresponding user story in `spec.md`.
- Tests in each story must be written and observed failing before implementation.

## Phase 1: Setup and Worktree Safety

**Purpose**: Establish a reproducible baseline without changing branches or losing current generic improvements.

- [X] T001 Record the current branch, modified/untracked files, focused test baseline, and ownership assumptions in `specs/005-generic-guided-workflows/implementation-baseline.md`
- [X] T002 [P] Create the project-specific contamination checklist covering private paths, provider/topic/language text, device forcing, one-video fixtures, and destructive migration risks in `specs/005-generic-guided-workflows/genericity-audit.md`

---

## Phase 2: Foundational Regression Locks

**Purpose**: Protect reusable improvements already present in the dirty diff before refactoring shared runtime paths.

**⚠️ CRITICAL**: Complete these neutral regression locks before changing the same production modules.

- [X] T003 [P] Add neutral regression tests for camera-source gain aliases, loudness-preset selection, cross-platform grade scratch paths, and caption boundary clamping in `tests/test_audio_gain.py`, `tests/test_grade.py`, and `tests/test_shorts_captions.py`
- [X] T004 [P] Add neutral regression tests for canonical locator/path fallback, Shorts preservation, final transcript placement, and delivered-QC state retention in `tests/test_project_inventory.py`, `tests/test_reconstruction_bundle.py`, and `tests/test_shorts_delivery.py`
- [X] T005 [P] Add A/V duration and requested-output-length regression coverage for the current FFmpeg `-shortest` behavior in `tests/test_render_duration.py`
- [X] T006 Make the foundational regression tests pass while preserving user-owned changes; remove `ffmpeg_filter_file_arg()` only if the use audit proves it unreachable in `src/avo/audio_gain.py`, `src/avo/grade.py`, `src/avo/render.py`, `src/avo/project_inventory.py`, `src/avo/shorts_captions.py`, `src/avo/shorts_delivery.py`, and `src/avo/timeline/reconstruction.py`
- [X] T007 Run the Phase 2 focused tests and record commands, results, and any intentionally deferred project-only failures in `specs/005-generic-guided-workflows/implementation-baseline.md`

**Checkpoint**: Current reusable behavior is protected by neutral core tests; story work may begin.

---

## Phase 3: User Story 1 — Always Know the Current Step (Priority: P1) 🎯 MVP

**Goal**: Every AVO-owned response ends with verified workflow, current step/status, next step, and next expected update guidance.

**Independent Test**: Exercise start, progress, approval, blocked, resumed, and completed examples and scan all 51 `/avo.*` wrappers plus the three entry skills for the required workflow metadata and final response block.

### Tests for User Story 1

- [X] T008 [P] [US1] Add failing contract tests for allowed statuses, durable-state authority, approval/input wording, blocker wording, completion wording, and final-block placement in `tests/test_avo_step_status_contract.py`
- [X] T009 [P] [US1] Extend wrapper/entry-skill scans to require exactly one workflow-step declaration, state source, stopping conditions, valid-next-command declaration, and shared-contract link in `tests/test_avo_commands.py` and `tests/test_timeline_command_runtime.py`

### Implementation for User Story 1

- [X] T010 [US1] Add the canonical response footer, durable-state mapping, and start/progress/approval/blocked/completion examples in `agent-skills/avo-pipeline/references/step-status.md`
- [X] T011 [US1] Require loading and applying the shared step-status contract from `agent-skills/avo/SKILL.md`, `agent-skills/avo-pipeline/SKILL.md`, and `agent-skills/avo-provider/SKILL.md`
- [X] T012 [US1] Add workflow steps, durable state source, stopping conditions, valid next commands, and the shared response-contract instruction to all 51 files in `commands/avo/*.md`
- [X] T013 [US1] Add command-specific step/state/gate/next-command mappings to every routed command reference listed by `agent-skills/avo-pipeline/references/command-map.md` in `agent-skills/avo-pipeline/references/*.md`
- [X] T014 [P] [US1] Document the response contract, resume behavior, concise footer rule, and prompt-authoring examples in `docs/avo-agent-step-status.md` and `docs/avo-commands.md`
- [X] T015 [US1] Run `tests/test_avo_step_status_contract.py`, `tests/test_avo_commands.py`, and `tests/test_timeline_command_runtime.py`; publish a non-leading human comprehension protocol and record real results or an explicit recruitment-pending state without fabrication in `docs/avo-agent-step-status-usability.md` and `specs/005-generic-guided-workflows/verification.md`

**Checkpoint**: Guided AVO responses work independently of all runtime media changes.

---

## Phase 4: User Story 2 — Configure Optional Reusable Behavior (Priority: P1)

**Goal**: Optional invocation and persistent settings have explicit controls, safe defaults, deterministic precedence, validation, provenance, and documentation.

**Independent Test**: Resolve a neutral example through global/provider/registry/project/invocation scopes, verify the effective values and winning sources, reject invalid combinations before work, and confirm private paths are redacted from user-facing summaries.

### Tests for User Story 2

- [X] T016 [P] [US2] Add failing unit tests for field-by-field precedence, array replacement, explicit/default provenance, deterministic hashing, path normalization, and validation errors in `tests/test_settings.py`
- [X] T017 [P] [US2] Add failing documentation/CLI-contract tests requiring every new optional control to state purpose, applicability, default, accepted values, scope, failure behavior, examples, artifact effects, and the valid next workflow action in `tests/test_optional_capabilities.py`

### Implementation for User Story 2

- [X] T018 [US2] Implement immutable `EffectiveSetting` and field-by-field scoped resolution with source tracking and stable policy hashing in `src/avo/settings.py`
- [X] T019 [US2] Add reusable safe path resolution and user-facing redaction helpers for persistent/invocation settings in `src/avo/settings.py`
- [X] T020 [US2] Expose scoped settings inputs without whole-object replacement and preserve existing transcription/model behavior in `src/avo/video_context.py`
- [X] T021 [US2] Add the invocation-versus-persistent decision table and scope precedence contract to `agent-skills/avo-pipeline/references/arguments.md` and `docs/optional-capabilities.md`
- [X] T022 [US2] Run `tests/test_settings.py` and `tests/test_optional_capabilities.py` and record the independent US2 result in `specs/005-generic-guided-workflows/verification.md`

**Checkpoint**: Reusable settings can be validated and inspected without Watch, Shorts, or delivery execution.

---

## Phase 5: User Story 3 — Keep Every Shorts Batch in One Canonical Place (Priority: P1)

**Goal**: Request, plans, status, approvals, work, delivery, transcripts, logs, and manifests resolve from one project-owned batch identity.

**Independent Test**: Resolve a default and supported nested batch root, run all stages, and verify consistent paths, v1.1 split-delivery rejection, v1.0 compatibility warning, atomic index discovery, and reconstruction/cleanup preservation.

### Tests for User Story 3

- [X] T023 [P] [US3] Add failing path tests for default/nested roots, Windows/POSIX normalization, containment, traversal, batch mismatch, plan-location checks, index collisions, and legacy inference in `tests/test_shorts_paths.py`
- [X] T024 [P] [US3] Add failing schema tests for `batchRoot`, `batchRootSource`, `planVersion`, atomic Shorts index entries, and v1.0 compatibility in `tests/test_shorts_contract.py`
- [X] T025 [P] [US3] Add failing integration tests for request/approval snapshots, stage-consistent work paths, canonical promotion, split-delivery rejection, legacy warning, and preserved delivery artifacts in `tests/test_shorts_batch_integration.py`, `tests/test_shorts_delivery.py`, and `tests/test_reconstruction_bundle.py`

### Implementation for User Story 3

- [X] T026 [US3] Implement immutable `ShortsBatchPaths`, containment validation, default/nested resolution, plan validation, and legacy inference in `src/avo/shorts_paths.py`
- [X] T027 [US3] Add strict Shorts index schema and v1.1 batch-root/status fields in `schemas/avo.shorts-index.schema.json`, `schemas/avo.shorts-plan.schema.json`, and `schemas/avo.shorts-status.schema.json`
- [X] T028 [US3] Route `validate`, `resolve`, `build`, `qc`, `status`, and `promote` through the canonical resolver and add `--raw-dir`/`--batch-dir` controls in `src/avo/shorts.py`
- [X] T029 [US3] Snapshot external requests and approval manifests immutably and update `shorts.index.json` atomically before expensive work in `src/avo/shorts_paths.py` and `src/avo/shorts.py`
- [X] T030 [US3] Derive work/delivery/transcript/log paths from `ShortsBatchPaths`, preserve index/request/plan/status/approval/delivery roots, and exclude documented scratch in `src/avo/shorts_delivery.py` and `src/avo/timeline/reconstruction.py`
- [X] T031 [US3] Enforce canonical v1.1 delivery, record v1.0 `legacyExternalDelivery`, and emit actionable deprecation guidance for `--delivery-dir` in `src/avo/shorts.py` and `src/avo/shorts_delivery.py`
- [X] T032 [US3] Document the canonical tree, supported nested override, preservation boundary, compatibility window, and CLI examples in `docs/shorts-batch-paths-and-lineage.md`, `commands/avo/shorts.md`, and `agent-skills/avo-pipeline/references/shorts.md`
- [X] T033 [US3] Run the US3 path/contract/integration/reconstruction tests and record the independent result in `specs/005-generic-guided-workflows/verification.md`

**Checkpoint**: A single-range legacy batch and a v1.1 batch both use verifiable, discoverable storage without implementing multi-segment assembly yet.

---

## Phase 6: User Story 4 — Preserve Ordered Multi-Segment Lineage (Priority: P1)

**Goal**: One Short may use discontinuous or reordered source segments while planning, captions, media, review windows, hashes, logs, and delivery preserve exact declared order.

**Independent Test**: Build a three-segment candidate ordered `10–12`, `30–32`, `20–22`; verify cumulative output mapping, duration, order-sensitive hashes, seam-safe captions/media, exact logs/manifests, and unchanged v1.0 normalization semantics.

### Tests for User Story 4

- [X] T034 [US4] Add neutral v1.1 request/transcript/media fixtures with reordered, overlapping-approved, invalid-overlap, zero-duration, and changed-fingerprint cases in `tests/fixtures/shorts/planning-v11/`
- [X] T035 [P] [US4] Add failing conditional v1.0/v1.1 schema tests for source identity, required/forbidden range fields, segment order, evidence, overlap approval, and stable plan lineage in `tests/test_shorts_contract.py`
- [X] T036 [P] [US4] Add failing planner tests for legacy normalization, exact reorder, transcript evidence concatenation, duration/output mapping, duplicate detection, source bounds, fingerprint changes, and no enclosing range in `tests/test_shorts_plan.py`
- [X] T037 [P] [US4] Add failing caption tests for per-segment corrections, cumulative offsets, forced seam boundaries, globally unique IDs, and segment-aware correction audit in `tests/test_shorts_captions.py`
- [X] T038 [P] [US4] Add failing unit and representative FFmpeg integration tests for declared-order picture/dialogue assembly, 30 ms seam safety, summed duration, and no inserted gap in `tests/test_shorts_media.py`
- [X] T039 [P] [US4] Add failing delivery tests for ordered base/insertion lineage, rights basis, sponsorship/affiliate/review-unit disclosures, privacy/safety/consent evidence, AI-use evidence, approvals, prepared hashes, transcript sidecars, `EDITLOG.md`, and `SOURCE-LOG.md` in `tests/test_shorts_delivery.py` and `tests/test_shorts_batch_integration.py`

### Implementation for User Story 4

- [X] T040 [US4] Implement conditional request v1.0/v1.1 and plan v1.1 `sourceSegments` contracts without permitting contradictory `sourceRange` in `schemas/avo.shorts-batch.schema.json`, `schemas/avo.shorts-plan.schema.json`, and `schemas/avo.shorts-composition.schema.json`
- [X] T041 [US4] Normalize v1.0 ranges to one in-memory segment and resolve/validate/hash ordered v1.1 segments with cumulative output maps in `src/avo/shorts_plan.py`
- [X] T042 [US4] Apply corrections in source time, remap each segment to output time, force phrase breaks at seams, and reindex IDs globally in `src/avo/shorts_captions.py`
- [X] T043 [US4] Prepare and concatenate ordered picture/dialogue segments deterministically with current seam protection and exact duration reporting in `src/avo/shorts_media.py`
- [X] T044 [US4] Write/hash `prepared-lineage.json`, bind it into composition identity, and add every segment seam to required Watch windows in `src/avo/shorts.py` and `schemas/avo.shorts-composition.schema.json`
- [X] T045 [US4] Preserve ordered segment and insertion lineage, approvals, rights/license references, sponsorship/affiliate/review-unit disclosures, privacy/safety/consent evidence, AI-use evidence, and final transcript sidecars in machine-readable/Markdown delivery records in `src/avo/shorts_delivery.py`
- [X] T046 [US4] Run all US4 contract/planner/caption/media/delivery tests and record the independent result in `specs/005-generic-guided-workflows/verification.md`

**Checkpoint**: Ordered discontinuous/reordered Shorts are independently reconstructable without Watch policy or master-fidelity work.

---

## Phase 7: User Story 5 — Configure Watch for the Actual Project (Priority: P2)

**Goal**: Watch execution and prompts use generic defaults plus explicit scoped policy/context, while refusal, malformed output, uncertainty, and insufficient coverage remain fail-closed and distinguishable.

**Independent Test**: Resolve unrelated format/language/device policies, inspect them without running Watch, exercise echoed JSON/refusal/malformed/coverage paths, and verify evidence records effective sources, prompt hash, actual tool/model identity, outcome kind, and raw attempts.

### Tests for User Story 5

- [X] T047 [P] [US5] Add failing policy tests for defaults, precedence, `inherit`, device values, bounds, working-directory resolution, context omission, policy hashing, and invalid combinations in `tests/test_watch_policy.py`
- [X] T048 [P] [US5] Add failing schema/config tests for global/provider/registry/project Watch settings and backward-compatible existing manifests in `tests/test_project_schema.py`, `tests/test_provider_schema.py`, and `tests/test_video_registry.py`
- [X] T049 [P] [US5] Extend adapter tests for generic prompts, last-valid-object selection, echoed JSON, UTF-8 replacement, explicit CPU/GPU behavior, bounded repair, refusal, uncertainty, malformed output, tool failure, and coverage in `tests/test_watch_adapter.py`
- [X] T050 [P] [US5] Add failing review/CLI tests for `review policy`, invocation overrides, two unrelated projects with conflicting format/language/resource policies and no cross-project leakage, context forwarding, policy-hash evidence invalidation, raw attempts, and preserved human-judgment state in `tests/test_review_runner.py` and `tests/test_cli_review.py`

### Implementation for User Story 5

- [X] T051 [US5] Add optional strict Watch settings to `config/avo.config.json`, `schemas/avo.project.schema.json`, `schemas/avo.video.schema.json`, and provider `routingOverrides.watch` validation in `providers/avo.provider.schema.json`
- [X] T052 [US5] Implement `WatchPolicy`, scoped resolution, validation, effective-source payload, prompt context, and generic prompt construction in `src/avo/adapters/understand/watch_policy.py`
- [X] T053 [US5] Merge provider `routingOverrides.watch`, registry `defaults.watch`, and project `watch` through shared provenance without changing existing model/transcription precedence in `src/avo/video_context.py`
- [X] T054 [US5] Add read-only `review policy` plus all documented `--watch-*` invocation controls and preflight validation in `src/avo/cli.py`
- [X] T055 [US5] Remove hardcoded model, repository work root, forced CPU, talking-head, language, provider/topic text, and fixed frame budgets; apply resolved policy/context in `src/avo/adapters/understand/watch_skill.py`
- [X] T056 [US5] Select the last schema-valid object, preserve every raw attempt, separate analysis repair from tool retries, and emit `outcomeKind`, policy/context, prompt hash, and actual tool/model identity in `src/avo/adapters/understand/watch_skill.py`
- [X] T057 [US5] Forward resolved policy/context/windows/transcript facts, retain human-judgment/refusal state, and bind policy hash/outcome kind into candidate evidence in `src/avo/timeline/review_runner.py` and `schemas/avo.review-evidence.schema.json`
- [X] T058 [US5] Apply the same resolved Watch policy to delivery-created review runners and make policy changes stale previous evidence in `src/avo/cli.py` and `src/avo/timeline/delivery.py`
- [X] T059 [US5] Document defaults, precedence, flags, inspection, hardware behavior, generic prompt inputs, retries, and fail-closed outcomes in `docs/watch-review-policy.md`, `commands/avo/watch.md`, `agent-skills/avo-pipeline/references/watch.md`, and `agent-skills/avo-pipeline/references/arguments.md`
- [X] T060 [US5] Run the US5 policy/schema/adapter/review/CLI tests and record the independent result in `specs/005-generic-guided-workflows/verification.md`

**Checkpoint**: Watch is configurable across projects without embedding one project's subject, language, format, paths, or hardware decisions.

---

## Phase 8: User Story 6 — Prove Delivery Fidelity from Canonical Lineage (Priority: P2)

**Goal**: Pre-master/delivery review proves the candidate matches its declared profile and actual picture-carrying ancestry, including approved transformations and prohibited proof/proxy use.

**Independent Test**: Validate native output, intentional scale-down, declared/undeclared reframe, proof/proxy base ancestry, lower-resolution overlay policy, codec-scoped bitrate, changed policy, stale locks, missing lineage, and candidate/materialization hash mismatch.

### Tests for User Story 6

- [X] T061 [P] [US6] Add failing materialization schema and compatibility tests for old cut proofs and strict v1.1 assembly records in `tests/test_materialization_schema.py`
- [X] T062 [P] [US6] Replace project-assumption tests with failing profile/lineage cases for native, scale-down, reframe, role policy, codec-scoped encoding, prohibited intermediates, and blocked prerequisites in `tests/test_source_fidelity_qc.py`
- [X] T063 [P] [US6] Add failing graph-builder tests proving ordered CMap base ancestry, compiled overlays/generators, transform edges, stable hashes, and exclusion of ignored Tracks base metadata in `tests/test_picture_lineage.py`
- [X] T064 [P] [US6] Add failing assembly-materialization tests for complete revision locks, render contract, lineage/policy hashes, immutable reuse, output fingerprint, and stale collisions in `tests/test_timeline_materialize.py` and `tests/integration/test_tracks_render_runtime.py`
- [X] T065 [P] [US6] Add failing review tests for required pre-master/deliver materialization, dependency derivation, blocked classifications, exact offending nodes, and policy staleness in `tests/test_review_runner.py` and `tests/test_cli_review.py`
- [X] T066 [P] [US6] Add failing delivery tests for copied-master byte verification and retained materialization/policy/lineage references in `tests/test_delivery_service.py`

### Implementation for User Story 6

- [X] T067 [US6] Add strict v1.1 assembly/cut materialization and optional structured fidelity-evidence details to `schemas/avo.materialization.schema.json` and `schemas/avo.review-evidence.schema.json`
- [X] T068 [US6] Implement resolved `DeliveryFidelityPolicy`, render-contract validation, codec/role rules, ordered evaluation, and blocked-versus-defect disposition in `src/avo/delivery_fidelity.py`
- [X] T069 [US6] Implement deterministic picture-lineage nodes/edges/hash construction and current-lock verification from actual renderer contributors in `src/avo/timeline/picture_lineage.py`
- [X] T070 [US6] Add immutable assembly materialization with CMap/Sync/BMap/Tracks locks, projection/render/policy/lineage/output hashes, producer identity, and reuse protection in `src/avo/timeline/materialize.py`
- [X] T071 [US6] Route Tracks/assembly rendering through the new materialization service instead of returning an unbound renderer output in `src/avo/cli.py` and `src/avo/adapters/media/timeline_render.py`
- [X] T072 [US6] Refactor current `source-fidelity` QC into a thin canonical materialization/policy evidence adapter with no exact-source-dimension or universal-bitrate assumptions in `src/avo/adapters/qc/source_fidelity.py`
- [X] T073 [US6] Pass canonical materialization into deterministic QC, classify missing/stale/invalid lineage as blocked, and retain exact policy/materialization/lineage details in `src/avo/adapters/qc/registry.py`, `src/avo/timeline/review.py`, and `src/avo/timeline/review_runner.py`
- [X] T074 [US6] Require `--materialization` for pre-master/deliver, derive dependencies from its lock, and include materialization/lineage/policy hashes in candidate identity in `src/avo/cli.py`
- [X] T075 [US6] Verify delivered master bytes and persist canonical materialization, policy, and lineage references in `src/avo/timeline/delivery.py`
- [X] T076 [US6] Document profile resolution, allowed transformations, contributor roles, fail/blocked meanings, migration, and remediation in `docs/delivery-fidelity.md`, `commands/avo/deliver.md`, and `agent-skills/avo-pipeline/references/deliver.md`, then record the US6 focused-test result in `specs/005-generic-guided-workflows/verification.md`

**Checkpoint**: Pre-master/delivery fidelity is profile-aware, lineage-backed, fail-closed, and independently testable.

---

## Phase 9: Polish and Cross-Cutting Validation

**Purpose**: Prove the six increments work together and that no project-specific behavior leaked into generic AVO.

- [X] T077 [P] Cross-check every new flag/config field/default/example/migration path and valid next workflow action against runtime behavior; verify any platform-named delivery profile against current official platform documentation and record its source/access date in `docs/optional-capabilities.md`, `docs/shorts-batch-paths-and-lineage.md`, `docs/watch-review-policy.md`, and `docs/delivery-fidelity.md`
- [X] T078 [P] Add and run a repository-purity scan for provider names, private footage/tool paths, hardcoded language/topic/format, forced device policy, and one-video core fixtures in `tests/test_generic_code_purity.py`
- [X] T079 Execute every scenario in `specs/005-generic-guided-workflows/quickstart.md` that does not require unavailable external media/tools and record evidence/skips in `specs/005-generic-guided-workflows/verification.md`
- [X] T080 Run `npm run test:projects` to confirm existing footage-project compatibility and record results without moving project-specific fixtures into core in `specs/005-generic-guided-workflows/verification.md`
- [X] T081 Run `pytest -m "not project"`, `npm run test:unit`, and the focused new suites; record exact commands/results in `specs/005-generic-guided-workflows/verification.md`
- [X] T082 Run `npm run quality`, resolve only feature-related failures without speculative cleanup, and record the final gate result in `specs/005-generic-guided-workflows/verification.md`
- [X] T083 Re-run the constitution and genericity audits for editorial truth, format neutrality, accessibility/caption seams, rights/source retention, immutable versions, review gates, QC, branch preservation, and repository purity in `specs/005-generic-guided-workflows/verification.md`

---

## Dependencies and Execution Order

### Phase dependencies

- **Phase 1 Setup**: Starts immediately; changes only feature planning records.
- **Phase 2 Foundation**: Depends on T001; locks current generic behavior before refactoring.
- **US1 Guided responses**: Depends on Phase 2; no runtime-story dependency.
- **US2 Optional settings**: Depends on Phase 2; supplies shared provenance used by US5 and US6.
- **US3 Canonical Shorts paths**: Depends on Phase 2; no dependency on US1/US2.
- **US4 Ordered segments**: Depends on US3 canonical paths/index so new plans and artifacts have one stable root.
- **US5 Watch policy**: Depends on US2 scoped settings; otherwise independently testable.
- **US6 Delivery fidelity**: Depends on US2 scoped settings and should integrate after US5's `ReviewRunner` evidence changes to avoid conflicting edits.
- **Phase 9 Polish**: Depends on all selected stories.

### User story dependency graph

```text
Foundation ─┬─> US1
            ├─> US2 ─> US5 ─> US6
            └─> US3 ─> US4
                 US2 ─────────> US6
```

US1 and US3 may begin in parallel after Foundation. US2 may also begin in parallel. US4 waits for US3; US5 waits for US2; US6 waits for the shared settings and ReviewRunner integration contracts.

### Within each story

1. Add the story's failing tests.
2. Implement pure models/policies/resolvers.
3. Integrate CLI/adapters/artifacts.
4. Update prompt/user documentation.
5. Run the independent story test and record evidence.

---

## Parallel Execution Examples

### User Story 1

- T008 and T009 can run together; T014 can proceed while T012/T013 update prompt surfaces.

### User Story 2

- T016 and T017 can run together; implementation then proceeds T018 → T019/T020 → T021.

### User Story 3

- T023, T024, and T025 can be authored together; implementation proceeds T026/T027 → T028/T029 → T030/T031.

### User Story 4

- After T034 creates fixtures, T035–T039 can run in parallel; implementation proceeds schema/planner before caption/media/delivery integration.

### User Story 5

- T047–T050 can run in parallel; schema/policy resolution T051–T053 precedes CLI/adapter/runner work T054–T058.

### User Story 6

- T061–T066 can run in parallel; implement policy/graph/schema T067–T069 before materialization and review/delivery integration T070–T075.

---

## Implementation Strategy

### MVP first: User Story 1

1. Complete Setup and Foundational regression locks.
2. Complete US1 shared response contract and all 51 wrappers.
3. Stop and run the independent US1 tests.
4. Demonstrate predictable start/progress/approval/blocked/completed responses before touching media runtime behavior.

### Incremental delivery

1. **MVP**: US1 gives immediate workflow orientation across AVO.
2. **Reusable control foundation**: US2 makes optional behavior explicit and inspectable.
3. **Shorts correctness**: US3 then US4 provide canonical storage and truthful ordered lineage.
4. **Review portability**: US5 removes project/hardware assumptions from Watch.
5. **Master safety**: US6 proves delivery fidelity from canonical ancestry/profile.
6. Run Phase 9 only after all desired stories are integrated.

### Parallel team strategy

- Track A: US1 prompt contract.
- Track B: US2 settings followed by US5 Watch.
- Track C: US3 paths followed by US4 ordered segments.
- After US2/US5 stabilize `ReviewRunner`, integrate US6 fidelity in the shared runtime files.

## Notes

- Do not create, switch, rename, or delete branches.
- Do not overwrite unrelated modified/untracked files; patch current diffs in place.
- Keep one-video fixtures under `tests/projects/` or external footage projects.
- New core fixtures must use neutral subjects, languages, providers, and paths.
- Do not update `CHANGELOG.md` until the user confirms the implementation is 100% finished.
- Stop for human review if legal, policy, privacy, factual, sponsorship, or disclosure uncertainty becomes material.
