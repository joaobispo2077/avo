# Research: Generic Guided AVO Workflows

## Decision 1: Preserve the pragmatic AVO architecture

**Decision**: Add small pure modules for reusable path/policy resolution and extend the existing Shorts, Watch, timeline, QC, schema, and prompt packages in place.

**Rationale**: The repository is one local Python CLI/orchestrator. The real boundaries are the filesystem, FFmpeg/FFprobe, and Watch subprocess. `shorts_paths.py` and `watch_policy.py` remove duplicated policy without introducing artificial domain layers.

**Alternatives considered**: A new Clean Architecture tree was rejected as disproportionate. Keeping all logic in `shorts.py` and `watch_skill.py` was rejected because several stages already disagree about paths and the adapter currently mixes execution with project-specific policy.

## Decision 2: Make scope precedence deterministic and inspectable

**Decision**: Resolve persistent Watch values field-by-field in `global → provider routingOverrides → registry defaults → project` order and apply explicit invocation flags last. Return both the effective value and its source for every field.

**Rationale**: Whole-object replacement loses safe defaults and makes the winning scope opaque. Invocation values must not persist; provider/project values must be schema-validated and documented.

**Alternatives considered**: Environment variables remain supported only for executable/model runtime integration already owned by Watch; they are not the public editorial policy API. Silent inference from machine hardware or project text was rejected.

## Decision 3: One canonical Shorts batch root

**Decision**: Resolve all batch artifacts from `<rawDir>/edit/shorts/<batchId>/`, or from an explicit `--batch-dir` whose resolved path remains inside `<rawDir>/edit/shorts/` and whose basename matches the immutable batch identity.

**Rationale**: Delivery location is correctness and preservation state, not a rendering convenience. A single resolver prevents current `plans/shorts/<batch>` and `plans/delivery/<batch>` drift.

**Alternatives considered**: Independent output/delivery overrides were rejected because they split the preservation boundary. Arbitrary external destinations were rejected because AVO session outputs belong under the footage project's `edit/` directory. Existing v1.0 plans retain a read-only compatibility path rather than being moved.

## Decision 4: Versioned ordered source lineage

**Decision**: Version 1.1 gives the request's primary source a stable `sourceId` and declares one or more ordered `sourceSegments[]` per candidate. Plans resolve each segment to immutable source/transcript fingerprints plus source and output boundaries. A candidate-wide speed applies to every segment in v1.1; multi-source transcript arbitration remains out of scope.

**Rationale**: A single enclosing range cannot represent removed gaps, reordering, or multiple sources. Explicit output offsets make captions, review windows, manifests, and reconstruction deterministic.

**Alternatives considered**: Keeping `sourceRange` beside `sourceSegments` in new files was rejected because the two can contradict. Per-segment speed was deferred because it expands audio/caption semantics without a current requirement. v1.0 inputs normalize to one segment in memory; new writes never synthesize an enclosing range.

## Decision 5: Segment-aware caption and media assembly

**Decision**: Validate and extract each segment independently, apply transcript corrections in source time, map corrected words into sequential output time, force a phrase break at every segment seam, and concatenate segment media in declared order with existing seam-safety behavior.

**Rationale**: This preserves meaning and makes exact join windows available to Watch. Forcing phrase breaks avoids captions that visually imply continuous speech across an editorial cut.

**Alternatives considered**: Selecting one enclosing transcript window or sorting by source time was rejected because both destroy declared order. Allowing phrases to bridge seams was rejected for readability and truthfulness.

## Decision 6: Watch policy is configuration; Watch safety is not optional

**Decision**: Configure Whisper model, device, frame budgets, analysis/tool retry budgets, work root, format, language, acceptance criteria, and risk notes without permitting required Watch gates to be disabled. Generic defaults are `device=auto`, model inherited from the resolved transcription default, 18 primary frames, 8 structured-repair frames, two analysis attempts, and three transient tool attempts. A read-only `review policy` command exposes effective values and sources.

**Rationale**: Hardware and project context vary, while exact-candidate review and fail-closed behavior are safety requirements. `auto` avoids forcing CPU or GPU. Bounded retry preserves predictable cost.

**Alternatives considered**: Hardcoded `medium`, forced `CUDA_VISIBLE_DEVICES=-1`, repository-private working roots, Portuguese/talking-head/topic text, and unlimited retries were rejected. A `--skip-watch` flag was rejected because it would bypass mandatory gates.

## Decision 7: Delivery fidelity comes from materialization lineage and a profile

**Decision**: Route assembly rendering through an immutable materialization with a structured `renderContract`, `pictureLineage`, and resolved fidelity policy. At pre-master/deliver, require that record and compare probed candidate media to the declared profile and transformed picture ancestry. Build ancestry from actual CMap base ranges and compiled overlay/generator contributors, not metadata-only Tracks entries.

**Rationale**: Dimensions, bitrate, filename, and byte size cannot prove that a master came from native approved media. Canonical CMap sources and exact render inputs can. Profile-aware checks allow legitimate reframes, rotation, crop, and codec differences.

**Alternatives considered**: Exact source-dimension equality and a universal 32 Mbps floor were rejected. Raw CLI dependency hashes without assembly ancestry were rejected. Missing lineage yields a blocked prerequisite, not an inferred pass or an ordinary content defect.

## Decision 8: One shared AVO response footer

**Decision**: Every AVO-owned skill/prompt response ends with exactly one concise block naming the workflow, current step/status, next step, and next expected update. Command documents declare their step sequence, gates, stops, durable-state mapping, and valid next commands.

**Rationale**: A shared contract gives users predictable orientation and makes omissions statically testable. Ending with the block matches the requested interaction pattern while leaving the result or blocker first.

**Alternatives considered**: Duplicating status prose throughout each response was rejected as noisy. Deriving state from chat memory was rejected because resumed sessions must use durable artifacts. Applying the rule to unrelated third-party skills or all general assistant conversation was rejected as out of scope.

## Decision 9: Compatibility is read/normalize, never auto-move

**Decision**: v1.0 Shorts requests/plans/status remain readable and are normalized at module boundaries. New outputs use v1.1. Legacy split `--delivery-dir` is accepted only for v1.0 plans during one documented compatibility window and is recorded as legacy; v1.1 uses the batch resolver exclusively.

**Rationale**: Immutable media/project artifacts must not be rewritten silently. A bounded compatibility path protects current projects while preventing new split layouts.

**Alternatives considered**: In-place migration and automatic file moves were rejected as destructive. Supporting split delivery forever was rejected because it preserves the original correctness defect.

## Decision 10: Verification follows existing quality gates

**Decision**: Use focused unit/contract tests first, integration tests for resolver-to-delivery and materialization-to-review flows, then `pytest -m "not project"`, `npm run test:unit`, and `npm run quality` before completion.

**Rationale**: The repository's Test Trophy and quality policy already define the required confidence level. Static prompt contract tests are cheap and cover the 51-command surface.

**Alternatives considered**: Project-only regression fixtures cannot replace generic core tests. End-to-end media rendering for every branch was rejected as slow; representative FFmpeg integration coverage plus pure policy tests is sufficient.

## Decision 11: Preserve generic worktree improvements, separate project contamination

**Decision**: Keep and test the reusable parts of the current diff: configurable camera-source gain keys, canonical locator/path fallback, cross-platform grade scratch handling, loudness-preset resolution, caption-boundary clamping, final-file transcript placement, Shorts delivery preservation, delivered-QC state retention, tolerant Watch UTF-8 capture, and schema-aware JSON extraction. Refactor the path/Watch/fidelity portions through the new contracts.

**Rationale**: These changes address cross-project failures found in the latest footage-project learndowns and do not encode one video's creative choices. Reverting the whole diff would lose valid reliability improvements; accepting it unchanged would ship the hardcoded Watch prompt/device/model/root and incomplete fidelity data flow.

**Alternatives considered**: Provider-specific prompt text, private tool roots, forced CPU/GPU decisions, and one-video paths remain outside generic AVO. Dead `ffmpeg_filter_file_arg()` should be removed only after its use audit; the new `-shortest` behavior must earn its place with duration and A/V-sync regression coverage.
