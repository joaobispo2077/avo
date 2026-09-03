# Data Model: Generic Guided AVO Workflows

## Shared configuration provenance

### EffectiveSetting

Represents one resolved optional setting.

| Field | Type | Rules |
|---|---|---|
| `value` | JSON value | Must satisfy the field's schema before expensive work |
| `source` | enum | `global`, `provider`, `registry`, `project`, or `invocation` |
| `explicit` | boolean | `true` when supplied outside the generic default |

Settings resolve per field. Arrays replace less-specific arrays; objects do not silently replace unrelated sibling fields.

## Canonical Shorts batch

### ShortsBatchPaths

Immutable value returned by the canonical resolver.

| Field | Type | Rules |
|---|---|---|
| `rawDir` | absolute path | Existing footage-project root |
| `batchId` | string | Matches `^[a-z0-9][a-z0-9-]*$` |
| `batchRoot` | absolute path | Inside `<rawDir>/edit/shorts/`; basename equals `batchId` |
| `rootSource` | enum | `canonical-default`, `invocation`, or `legacy-output` |
| `indexPath` | path | `<rawDir>/edit/shorts/shorts.index.json` |
| `requestRoot` | path | Equal to `batchRoot` |
| `plansDir` | path | `<batchRoot>/plans` |
| `statusPath` | path | `<batchRoot>/plans/shorts.status.json` |
| `approvalsDir` | path | `<batchRoot>/approvals` |
| `workDir` | path | `<batchRoot>/work` |
| `deliveryDir` | path | `<batchRoot>/delivery` |
| `mastersDir` | path | `<batchRoot>/delivery/masters` |
| `transcriptsDir` | path | `<batchRoot>/delivery/transcripts` |

Validation rejects traversal, batch-ID mismatch, a v1.1 plan outside `plansDir`, or a new split delivery root. A supported override may use a nested directory under `<rawDir>/edit/shorts/`, but the leaf remains `batchId` and is registered in the canonical index. The value is persisted in index/plan/status/delivery records so later stages do not re-guess it.

### ShortsSource

One stable source owned by a Shorts batch request.

| Field | Type | Rules |
|---|---|---|
| `sourceId` | string | Stable within the request; defaults to `master` only during v1.0 normalization |
| `masterPath` | path | v1.1 external input; copied only by reference, never modified |
| `transcriptPath` | path/null | Required before transcript-backed resolution for referenced segments |
| `expectedFingerprint` | SHA-256/null | If declared, must match before planning/building |
| `mediaFingerprint` | SHA-256 | Required in resolved plan |
| `transcriptFingerprint` | SHA-256/null | Required when a transcript is used |

Version 1.1 remains a one-primary-source batch contract. `sourceId` makes lineage explicit without expanding this feature into multi-source transcript arbitration.

### RequestedSourceSegment

| Field | Type | Rules |
|---|---|---|
| `order` | integer | One-based and equal to array position; never auto-sorted |
| `sourceId` | string | Must match the request source |
| `startSec` | finite number | `>= 0` |
| `endSec` | finite number | `> startSec` and within source duration |
| `rationale` | string | Non-empty editorial reason |
| `evidenceReference` | string | Non-empty reference to approval/transcript/review evidence |
| `overlapApprovalReference` | string/null | Required only when a later segment overlaps an earlier segment |

### ResolvedSourceSegment

Extends the requested segment with immutable and output-time data.

| Field | Type | Rules |
|---|---|---|
| `segmentId` | string | Stable `<shortId>-sNNN` |
| `sourceFingerprint` | SHA-256 | Must match the source at build time |
| `outputStartSec` | number | Cumulative edited duration of earlier declared segments |
| `outputEndSec` | number | `outputStartSec + (endSec-startSec)/speed` |
| all requested fields | same | Preserved verbatim after validation |

The ordered list is identity-bearing. Hashing, duplicate detection, preparation, captions, review, logs, and delivery consume array order, not chronological source order.

### PreparedLineage

Candidate-bound record written beside prepared proof assets.

| Field | Type |
|---|---|
| `planHash` | SHA-256 |
| `shortId` | string |
| `sourceSegments` | ordered `ResolvedSourceSegment[]` |
| `preparedVideo` | locator, SHA-256, duration |
| `preparedDialogue` | locator, SHA-256, duration |
| `joinWindows` | output-time windows with `segmentId` pair and reason |
| `lineageHash` | SHA-256 over all preceding identity-bearing fields |

## Watch review

### WatchPolicy

| Field | Type | Default/effective rule |
|---|---|---|
| `whisperModel` | string | `inherit`; resolves from effective AVO transcription model |
| `device` | string | `auto`; accepts `auto`, `cpu`, `cuda`, `cuda:N` |
| `maxFrames` | integer | `18`, range `1..64` |
| `repairMaxFrames` | integer | `8`, range `1..64`, `<= maxFrames` |
| `analysisAttempts` | integer | `2`, range `1..3` |
| `toolAttempts` | integer | Existing runner default `3`, range `1..3` |
| `workingDirectory` | path/null | Candidate directory when omitted; relative values resolve from `rawDir` |
| `format` | string/null | Omitted from prompt when undeclared |
| `language` | string/null | Omitted from prompt when undeclared |
| `acceptanceCriteria` | string[] | Empty generic default; arrays replace by scope |
| `riskNotes` | string[] | Empty generic default; arrays replace by scope |
| `settingSources` | map | `EffectiveSetting.source` for every field |
| `policyHash` | SHA-256 | Hash of effective values and sources |

`device=cpu` alone sets `CUDA_VISIBLE_DEVICES=-1`. `auto`, `cuda`, and `cuda:N` never inherit that forced value. There is no enabled/disabled field because required review gates cannot be bypassed.

### WatchReviewContext

| Field | Type | Rules |
|---|---|---|
| `checkpoint` | enum | Current review checkpoint |
| `scope` | enum | `full` or `windows`; mandatory gates remain full |
| `requiredWindows` | array | Includes configured/runtime risk windows and deterministic-QC-required windows |
| `format` / `language` | string/null | Declared facts only |
| `acceptanceCriteria` | string[] | Checkpoint + configured criteria |
| `riskNotes` | string[] | Declared facts only |
| `transcriptRef` | locator/null | Exact candidate transcript |
| `terms` / `names` | string[] | Validated project facts |

### WatchEvidence

Adds `policy`, `reviewContext`, `promptSha256`, `outcomeKind`, and raw `attempts` to the existing candidate-bound Watch evidence. `outcomeKind` is one of `content`, `uncertainty`, `refusal`, `malformed`, `tool-error`, or `coverage`.

## Delivery fidelity

### RenderContract

Structured output expectations resolved before render.

| Field | Type | Rules |
|---|---|---|
| `profileId` | string | Stable declared profile |
| `purpose` | enum | `proof`, `master`, or `delivery` |
| `width` / `height` | integer | Positive declared output geometry |
| `displayAspectRatio` | string/number | Must agree with allowed transform result |
| `frameRate` | rational | Includes tolerance |
| `durationSeconds` | number/null | Includes explicit tolerance when constrained |
| `encodingRules` | object | Optional codec-family-specific rules; no universal bitrate floor |
| `allowedTransformations` | string[] | Examples: crop, reframe, rotate, scale-down, color-convert, encode |

### PictureLineageNode

| Field | Type | Rules |
|---|---|---|
| `nodeId` | string | Unique in materialization |
| `kind` | enum | `source`, `generated`, `intermediate`, `output` |
| `role` | string | Actual render role such as base, overlay, captions, or output |
| `mediaClass` | string | `camera-original`, `approved-master`, `proof`, `proxy`, `generated`, etc. |
| `locator` | string | Exact artifact reference |
| `sha256` | SHA-256 | Required for picture-carrying filesystem media |
| `pictureCarrying` | boolean | Controls fidelity ancestry traversal |
| `media` | object | Probe geometry, duration, frame rate, codec where applicable |

### PictureLineageEdge

Ordered directed transform from inputs to output. `operation` is one of trim, concat, crop, reframe, rotate, scale, grade/color, place/composite, captions, or encode. Parameters and approval reference are required when an operation changes geometry or editorial meaning.

### PictureLineage

Contains ordered nodes/edges, output root IDs, exact CMap/Sync/BMap/Tracks locks, raw fingerprints, projection hash, and `pictureLineageHash`. It is built from actual renderer contributors: CMap ranges for base picture and only compiled overlay roles. Ignored Tracks `base` metadata is not an ancestor.

### DeliveryFidelityPolicy

| Field | Type |
|---|---|
| `policyId` / `profileId` / `policyHash` | strings/hashes |
| `settingSources` | map |
| `renderContract` | `RenderContract` |
| `prohibitedBaseClasses` | string[]; defaults to `proof`, `proxy` |
| `roleRules` | map of role-specific allowances |

### DeliveryFidelityEvidence

Keeps existing evidence kind `source-fidelity` and adds structured details: policy/materialization/lineage hashes, output hash, root IDs, offending node IDs, and evaluated render contract.

Evaluation dispositions:

- `pass`: complete current lineage and profile; candidate satisfies both.
- `fail`: candidate or ancestry violates a declared rule.
- `blocked`: missing, stale, contradictory, or invalid prerequisite; represented as error/blocked review state rather than a content defect.
- `not-applicable`: checkpoints before pre-master/deliver.

## Guided workflow responses

### WorkflowDefinition

| Field | Type | Rules |
|---|---|---|
| `command` | string | `/avo.*` identity |
| `steps` | ordered string[] | User-understandable and complete |
| `stateSource` | string | Durable artifact or observed one-shot result |
| `stoppingConditions` | string[] | Gates, blockers, and completion |
| `validNextCommands` | string[] | Allowed next user actions |

### StepStatus

| Field | Type | Rules |
|---|---|---|
| `workflow` | string | Current `/avo.*` command |
| `currentStep` | string | One declared workflow step |
| `status` | enum | `not started`, `in progress`, `awaiting user`, `blocked`, `completed` |
| `nextStep` | string | Declared next step or `Workflow complete` |
| `nextExpectedUpdate` | string | Agent report or exact user action that triggers progress |

State mapping uses `pipeline-run.json`, `review.json`, `shorts.status.json`, `delivery-manifest.json`, or the observed one-shot result. Durable state wins over chat memory.

## State transitions

### Shorts batch

Existing status transitions remain authoritative: `draft → resolved → plan-approved → building-proofs → proofs-ready/proof-partial → proof-review → picture-locked → building-masters → master-qc → delivered`, with `blocked` reachable from any gated stage. v1.1 adds path/lineage validation before each expensive transition.

### Review

`reviewing → fixing → ai-passed` or `needs-human-judgment`/`blocked`; approval is a separate human-bound decision. Missing/stale fidelity prerequisites transition directly to `blocked`. A valid Watch uncertainty/refusal transitions to `needs-human-judgment`, not ordinary fail.

### Agent step status

`not started → in progress → awaiting user → in progress → completed`, with `blocked` reachable from any active step. A response may report only the state proven by its durable source.
