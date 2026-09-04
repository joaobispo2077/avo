# Feature Specification: Generic Guided AVO Workflows

**Feature Branch**: `N/A — current branch preserved`

**Created**: 2026-08-31

**Status**: Draft

**Input**: Make reusable AVO behavior explicitly configurable and documented, add canonical Shorts paths, ordered source lineage, configurable Watch review, lineage-fed delivery fidelity, and make every AVO skill response clearly tell the user their current and next workflow steps.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Always Know the Current Step (Priority: P1)

As an AVO user, I can tell where I am in a workflow, what just happened, what happens next, and what the agent will report next without understanding internal commands or artifacts.

**Why this priority**: A technically correct workflow still feels unreliable when the user cannot tell whether work is running, awaiting approval, blocked, or complete.

**Independent Test**: Invoke any AVO command at its initial, active, approval, blocked, and completed states and verify that each user-facing response identifies the current step, its status, the next step, and the expected next update.

**Acceptance Scenarios**:

1. **Given** a user starts an AVO workflow, **When** the agent acknowledges the request, **Then** it states the workflow, current step, current status, next step, and what the next progress update will cover.
2. **Given** work advances between stages, **When** the agent reports progress, **Then** it states what completed, the current step, the next step, and whether user action is required.
3. **Given** the workflow requires approval or information, **When** the agent prompts the user, **Then** it explains why the input is needed, what decision it controls, the exact expected response, and the step that follows.
4. **Given** a workflow is blocked, **When** the agent reports the blocker, **Then** it names the blocked step, evidence for the blocker, the action needed to unblock it, and the next update the user should expect.
5. **Given** a workflow completes, **When** the agent returns its final response, **Then** it identifies the completed step and offers the appropriate next AVO or Spec Kit action.

---

### User Story 2 - Configure Optional Reusable Behavior (Priority: P1)

As an AVO operator, I can enable optional reusable behavior explicitly, understand its default, and find documentation that explains when and why to use it.

**Why this priority**: Generic code must not silently impose one provider's format, hardware, language, or editorial choices on unrelated projects.

**Independent Test**: Inspect and exercise each optional capability with its default and explicit enabled/overridden states, then verify that user documentation describes availability, default behavior, scope, examples, and failure handling.

**Acceptance Scenarios**:

1. **Given** an optional capability exists, **When** the user does not select it, **Then** AVO applies the documented safe default without introducing provider- or project-specific behavior.
2. **Given** the user selects an optional capability, **When** the workflow resolves its configuration, **Then** the selected value and its source are visible in the plan or status shown to the user.
3. **Given** a provider or project overrides a reusable default, **When** the workflow starts, **Then** AVO reports the effective setting without exposing private paths or embedding the override into generic code.
4. **Given** an invalid or incompatible option, **When** validation runs, **Then** AVO stops before expensive work and explains the valid alternatives.

---

### User Story 3 - Keep Every Shorts Batch in One Canonical Place (Priority: P1)

As a creator, I can find a Shorts batch's request, plan, proofs, status, approvals, masters, transcripts, and delivery records under one predictable project-owned batch location.

**Why this priority**: Destination is part of correctness; files outside the canonical footage project can escape reconstruction, cleanup preservation, and delivery review.

**Independent Test**: Start a batch using defaults and again with an explicit supported destination, then verify every stage resolves the same batch identity and that delivered artifacts survive reconstruction and cleanup inventory.

**Acceptance Scenarios**:

1. **Given** a footage project and batch identity, **When** any Shorts stage resolves a path, **Then** it derives the same canonical batch location.
2. **Given** no destination override, **When** a batch is promoted, **Then** its masters and transcript sidecars land in the canonical batch delivery area.
3. **Given** an explicit supported destination override, **When** the workflow uses it, **Then** the effective destination is recorded and all subsequent stages use it consistently.
4. **Given** cleanup or reconstruction inventory runs, **When** a batch has immutable plans or delivered artifacts, **Then** those records are preserved while documented scratch proofs remain eligible for cleanup.

---

### User Story 4 - Preserve Ordered Multi-Segment Lineage (Priority: P1)

As an editor, I can define a Short from one or more ordered source segments, including discontinuous or reordered material, without falsifying the source range.

**Why this priority**: A single enclosing range cannot truthfully represent reordered arguments, removed gaps, or multi-part assemblies.

**Independent Test**: Create a Short from three ordered segments where the second source segment occurs later than the third, then verify planning, rendering, hashing, review, source logging, and delivery preserve that exact order.

**Acceptance Scenarios**:

1. **Given** a candidate with one segment, **When** it is planned, **Then** the existing simple-range workflow remains valid.
2. **Given** a candidate with multiple segments, **When** it is planned, **Then** every segment retains source identity, boundaries, order, rationale, and evidence reference.
3. **Given** segments are reordered, **When** the output is built, **Then** assembly follows declared order and never replaces it with an enclosing range.
4. **Given** a delivered Short, **When** its manifest or source log is inspected, **Then** a reviewer can reconstruct the ordered source lineage without chat history.

---

### User Story 5 - Configure Watch for the Actual Project (Priority: P2)

As an operator, I can configure Watch execution and review context for the current hardware, format, language, checkpoint, and risks without changing generic AVO code.

**Why this priority**: Review quality and resource use differ by machine and project, while the safety contract must remain consistent.

**Independent Test**: Review unrelated projects with different languages, formats, and resource policies, and verify each receives appropriate review context while malformed or uncertain results still fail closed.

**Acceptance Scenarios**:

1. **Given** no project-specific review policy, **When** Watch runs, **Then** it uses documented generic defaults and makes no topic, language, format, or hardware assumption.
2. **Given** a provider, project, or invocation supplies a supported review policy, **When** Watch runs, **Then** effective analysis depth, resource policy, and review context are recorded with the evidence.
3. **Given** checkpoint criteria and risk windows, **When** the review prompt is formed, **Then** it describes those facts rather than hardcoded project subject matter.
4. **Given** Watch refuses, returns malformed output, or is uncertain, **When** evidence is evaluated, **Then** AVO retries only within policy and otherwise routes to a blocked or human-judgment state.

---

### User Story 6 - Prove Delivery Fidelity from Canonical Lineage (Priority: P2)

As a reviewer, I can verify that a delivery candidate satisfies its declared output profile and comes from approved picture-carrying sources rather than an upscaled proof.

**Why this priority**: Filename labels, file size, and final dimensions alone cannot prove native-source fidelity.

**Independent Test**: Validate a native-source master, an upscaled proof assembly, a legitimate declared reframe, and a candidate with missing lineage; verify each receives the correct pass, fail, or blocked result.

**Acceptance Scenarios**:

1. **Given** a candidate and complete canonical lineage, **When** delivery fidelity is checked, **Then** the result compares the candidate with its declared output profile and picture-carrying ancestors.
2. **Given** a proof-resolution intermediate is used in a master assembly without an approved transformation, **When** fidelity is checked, **Then** delivery is blocked with the offending ancestor identified.
3. **Given** a declared crop, reframe, rotation, or other allowed transformation, **When** fidelity is checked, **Then** it is evaluated against that declared transformation rather than exact source dimensions alone.
4. **Given** required lineage or output-profile information is missing, **When** fidelity is checked, **Then** AVO fails closed and explains which earlier workflow step must be completed.

### Edge Cases

- A resumed conversation has artifact state but no reliable conversational memory of the last announced step.
- A command performs only diagnosis and has no render or approval stage.
- A command stops after one response, while a long-running command emits several progress updates.
- An optional setting is supplied by global, provider, project, and invocation scopes at the same time.
- A legacy Shorts request contains only `sourceRange`, while a new request contains one or many ordered segments.
- Two batches have similar names but different immutable identities.
- A destination override points outside the footage project or conflicts with cleanup preservation.
- Source segments overlap, have zero duration, reference changed source bytes, or exceed source duration.
- Watch configuration requests unavailable resources or an unsupported model.
- Watch returns valid-looking JSON echoed from the prompt before its actual analysis.
- A delivery is intentionally reframed from landscape to portrait or uses a codec with different bitrate efficiency.
- Canonical lineage is stale, incomplete, or disagrees with the candidate's materialization lock.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Every AVO-owned skill and `/avo.*` command MUST define a named sequence of user-understandable workflow steps.
- **FR-002**: Every user-facing AVO response MUST state the current workflow step and one of: not started, in progress, awaiting user, blocked, or completed.
- **FR-003**: Every user-facing AVO response MUST state the next step or explicitly state that the workflow is complete.
- **FR-004**: Every progress response MUST state what the next agent update will report or what user action will cause that update.
- **FR-005**: Every AVO prompt requesting user input MUST state why the input is needed, what it affects, the expected response, and the step that follows.
- **FR-006**: Step reporting MUST reflect verified workflow and artifact state rather than conversational guesswork.
- **FR-007**: Resumed workflows MUST reconstruct the current step from durable project state when available.
- **FR-008**: Step reporting MUST remain concise and must not obscure blockers, approval questions, results, or safety warnings.
- **FR-009**: Shared AVO guidance MUST provide one reusable response contract and examples for start, progress, approval, blocked, and completion states.
- **FR-010**: Every AVO command document MUST identify its workflow stages, gates, stopping conditions, and valid next commands.
- **FR-011**: An invocation-specific optional capability MUST have an explicit flag; an option that persists across runs MUST have a documented configuration field. Neither MAY activate implicitly when it is not universally applicable.
- **FR-012**: Each optional capability MUST document its purpose, applicability, default, accepted values, scope precedence, examples, validation failures, and effect on artifacts or review.
- **FR-013**: Effective optional settings and their source MUST be inspectable before expensive work or approval.
- **FR-014**: Generic defaults MUST NOT contain provider names, private paths, project subjects, assumed language, or machine-specific resource decisions.
- **FR-015**: Unsupported or incompatible option combinations MUST fail before expensive work with actionable alternatives.
- **FR-016**: AVO MUST define one canonical Shorts batch location from footage-project identity and immutable batch identity.
- **FR-017**: Request, plans, status, approvals, proofs, delivery, masters, transcript sidecars, logs, and manifests MUST resolve relative to the same batch location unless an explicit supported override is recorded.
- **FR-018**: Default promotion MUST place delivery artifacts in the same canonical batch tree recognized by reconstruction and cleanup preservation.
- **FR-019**: Delivery records and immutable planning/approval records MUST be preserved; documented scratch artifacts MAY remain cleanup candidates.
- **FR-020**: Every Shorts candidate MUST support an ordered list of one or more source segments.
- **FR-021**: Each source segment MUST preserve source identity, source boundaries, output order, rationale, and evidence reference.
- **FR-022**: Multi-segment planning, hashing, assembly, review, delivery manifests, edit logs, and source logs MUST preserve the exact declared order.
- **FR-023**: AVO MUST NOT replace discontinuous or reordered lineage with one enclosing source range.
- **FR-024**: Existing valid single-range requests MUST remain usable through a documented compatibility path that does not change their meaning.
- **FR-025**: Watch execution policy MUST support documented generic defaults and explicit global, provider, video-registry, project, or invocation overrides with deterministic precedence.
- **FR-026**: Watch execution policy MUST cover analysis depth, resource selection, working context, retry limits, and evidence capture without assuming one machine.
- **FR-027**: Watch review context MUST derive from checkpoint, format diagnosis, language, acceptance criteria, risk windows, transcript context, and declared project facts.
- **FR-028**: Watch review prompts MUST NOT embed unrelated subject matter, provider identity, language, or format assumptions.
- **FR-029**: Effective Watch policy and tool/model identity MUST be recorded with candidate-bound evidence.
- **FR-030**: Watch refusal, malformed output, insufficient coverage, and unresolved uncertainty MUST fail closed and remain distinguishable from a content defect.
- **FR-031**: Delivery fidelity MUST evaluate a candidate against its declared delivery profile, approved canonical lineage, and allowed transformations.
- **FR-032**: Delivery fidelity MUST identify every picture-carrying ancestor needed to prove the result was not assembled from an inappropriate proof or proxy.
- **FR-033**: Delivery fidelity MUST account for declared crop, reframe, rotation, aspect, resolution, frame-rate, duration, and encoding expectations where applicable.
- **FR-034**: Delivery quality limits MUST be profile-aware and MUST NOT assume one codec, one source resolution, or one universal bitrate.
- **FR-035**: Missing or stale lineage, profile, or materialization evidence MUST block pre-master and delivery review with an actionable prerequisite.
- **FR-036**: Review and delivery documentation MUST explain fidelity findings in user-understandable language while retaining exact offending artifact references.
- **FR-037**: Rights and source records for Shorts MUST retain segment lineage, inserted assets, rights references, and approval evidence through delivery.
- **FR-038**: The feature MUST include migration guidance for existing AVO commands, legacy single-range Shorts requests, and current project/provider settings.
- **FR-039**: The feature MUST provide user documentation and examples for all new controls, workflow-step reporting, canonical paths, segment lineage, Watch policy, and delivery fidelity behavior.
- **FR-040**: No private footage path, one-video helper, provider creative choice, or project-specific review prompt MAY be added to generic AVO code or shared defaults.

### Editorial And Platform Requirements

- **ER-001**: New options, path resolution, segment lineage, review policy, and step guidance MUST preserve creator intent, factual meaning, chronology, tone, and material disclosures unless explicitly approved.
- **ER-002**: Workflow-step guidance MUST NOT imply that format diagnosis, review, approval, rights, accessibility, or QC has passed before current evidence proves it.
- **ER-003**: Optional flags and configuration MUST NOT bypass the title/thumbnail promise, format diagnosis, canonical lineage, human approval, or final QC requirements.
- **ER-004**: Ordered segments and delivery-fidelity evidence MUST preserve the audio, visual, caption, accessibility, and source relationships needed to review the exact output.
- **ER-005**: Canonical delivery records MUST retain source, rights, disclosure, privacy, safety, and AI-use evidence required for release decisions.
- **ER-006**: Migrated and newly generated artifacts MUST retain immutable version identity, review gates, edit/source logs, and final-candidate QC status.

### Key Entities

- **Workflow Step Status**: The workflow name, current step, status, completed outcome, next step, required user action, and expected next update.
- **Optional Capability**: A reusable behavior with applicability, default, accepted choices, effective scope, source, validation rules, and documentation reference.
- **Shorts Batch Location**: The canonical project-owned location tied to an immutable batch identity and containing all planning, review, scratch, and delivery artifact classes.
- **Source Segment**: One ordered source contribution with source identity, boundaries, rationale, evidence, and output position.
- **Watch Policy**: Effective review execution and context choices plus their configuration source and evidence identity.
- **Delivery Fidelity Policy**: The declared output expectations, allowed transformations, quality constraints, and required lineage evidence for a review checkpoint.
- **Canonical Lineage**: Approved source-to-candidate ancestry, transformations, revisions, fingerprints, and materialization lock used to prove reconstruction and fidelity.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of shipped AVO-owned skills and `/avo.*` command prompts pass an automated audit requiring current step, status, next step, and expected next update guidance.
- **SC-002**: Using the documented human comprehension protocol, at least 90% of participants can correctly identify whether AVO is working, waiting for them, blocked, or complete from a single response. Implementation MUST ship the protocol and record available results; it MUST NOT fabricate participant results when recruitment has not occurred.
- **SC-003**: 100% of optional non-universal capabilities expose a documented explicit control or configuration field, and no audited generic default contains project/provider-specific literals.
- **SC-004**: A batch run without destination overrides places 100% of immutable plan, status, delivery, master, transcript, log, and manifest artifacts under one canonical batch tree.
- **SC-005**: Reconstruction and cleanup verification preserve 100% of delivered Shorts and immutable batch records while allowing documented scratch proofs to be identified separately.
- **SC-006**: Single-segment, discontinuous multi-segment, and reordered multi-segment acceptance cases retain exact source order and identities through delivery with zero flattened or fabricated ranges.
- **SC-007**: Two unrelated projects with different format, language, and resource needs can complete Watch review without modifying generic code or inheriting each other's review assumptions.
- **SC-008**: Delivery-fidelity acceptance tests correctly distinguish native-source delivery, declared reframing, proof upscaling, stale lineage, and missing lineage in every required checkpoint case.
- **SC-009**: Every new or changed capability has user documentation covering defaults, options, examples, failure behavior, artifact effects, and the next workflow action.
- **SC-010**: Existing valid single-range Shorts projects and unaffected AVO commands continue to complete their prior user journeys without requiring project-specific migration code.

## Assumptions

- “Every response and prompt” applies to AVO-owned skills, `/avo.*` commands, their progress commentary, approval prompts, and completion reports; it does not rewrite unrelated third-party skills or general assistant conversation.
- One concise shared step-status block can satisfy the communication contract; repeating status in every paragraph is neither required nor desirable.
- Optional behavior uses explicit command controls when invocation-specific and documented configuration when it must persist at provider or project scope.
- Existing scope precedence remains global, then provider routing overrides, then video-registry defaults, then project, then explicit invocation, with later and more specific values taking precedence when valid.
- The current branch is preserved in accordance with repository branch policy; the specification directory is independent of a Git branch.
- Existing canonical timeline artifacts are the authority for delivery lineage; chat history and filenames are not evidence.
- Editorial and provider-specific creative practices remain in footage projects or provider guidance unless separately generalized and approved.
