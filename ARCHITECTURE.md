# AVO architecture

AVO is a local-first modular monolith. `src/avo/` contains the bundled editing
engine and application orchestration; CLI and MCP expose the same operations.
Hexagonal architecture applies at real external-tool boundaries, not through a
mandatory domain/application/infrastructure directory template.

`AGENTS.md` remains the canonical agent instruction file. This document records
architecture and its evolution. Every architectural evolution must update this
root document with its responsibility, dependencies, compatibility and checks.

## Responsibilities and dependency direction

| Responsibility | Owner | Boundary |
| --- | --- | --- |
| Timeline decisions and lineage | `avo.timeline` | Canonical source clocks, revisions, approvals and proof contracts |
| External tools | `avo.adapters` | FFmpeg/FFprobe, transcription, visual review and motion backends |
| Proof composition | `avo.proof_composition` | Lazy construction of proof/sync adapters and native audio-rate probing |
| Application entry points | `avo.cli`, `avo.mcp` | Validate requests and compose concrete dependencies |
| Shorts planning | `avo.shorts_plan`, `avo.shorts_rules` | Resolve editorial parameters and pure mapping rules without media preparation |
| Media preparation | `avo.shorts_media` | Fingerprinted assets and deterministic tool execution |
| Persistence | Timeline stores and project contracts | Immutable revisions, atomic writes, hashes and compare-and-swap |

Use plain functions for shared rules. Reuse existing ports when tools need
substitution or isolated tests. Do not add service inheritance, singleton
registries, algorithm strategies or new dependencies for a single implementation.
The current skills' references to `helpers/` describe the former layout;
`src/avo/` owns the engine and `helpers/` contains compatibility shims.

## Invariants and compatibility

- Footage decisions and outputs live under the external raw directory's `edit/`.
- Proofs reconstruct only from canonical revisions and fingerprinted original
  sources. Approval, ancestry, synchronization and quiz protection are mandatory.
- Refactoring preserves serialized records, stable IDs, error behavior and public
  entry points. A prior proof is never reusable source media.
- Fingerprint formats and atomic JSON writers have different contracts. Shared
  mechanics must not erase validation, durability or representation differences.
- Python 3.10 remains supported. No new package dependency is required here.

## Import enforcement

`.importlinter` forbids adapters importing CLI/MCP, timeline importing CLI/MCP,
and core modules importing MCP registration. Timeline must not grow adapter
dependencies. Compatibility exceptions must be explicit, narrow and documented;
passing these contracts is not a claim that every application module is pure.

Two legacy bridges are currently allowed: `timeline.materialize` and
`timeline.initial_cut` may depend on `avo.proof_composition` when callers omit
explicit dependencies. This replaces direct adapter imports and tool execution,
but deliberately retains indirect coupling for backward compatibility. CLI
provides the render port and sample-rate probe explicitly. Remove these bridges
only through a separately approved migration of the optional-default APIs.
`initial_cut_proof_request` accepts an optional
`sample_rate_probe(selection, locator)` callable. Declared `sourceSampleRate`
takes precedence, and observed rates remain cached by source ID within a request.
Shorts planning/rules also have a contract forbidding media preparation and
adapter imports.

## Evolution: architecture audit follow-up (2026-10-10)

The audit inspected 173 Python modules, approximately 56,700 lines. Keep the
modular monolith: file size alone does not justify splitting modules.

Implemented changes, preserving current behavior:

1. Share stable-ID diff logic for CMap/BMap while retaining their actor intent,
   collection names, operation order and immutable revision behavior.
2. Share best-effort duration probing at the FFprobe adapter boundary; retain
   render/voiceover entry points and their `None` result on probe failure.
3. Share validator config lookup while retaining the missing-file fallback path.
4. Share cutting's selected-source-range conversion and remove unused private
   MCP `cli_group` flexibility.
5. Separate pure Shorts window/mapping rules and SFX metadata from preparation,
   retaining the old media module's exports and exception identity.
6. Move proof adapter construction and the initial-cut sample-rate subprocess to
   an outer composition boundary. Inject dependencies from CLI. Existing calls
   that omit them retain a documented compatibility bridge; this is a gradual
   migration, not removal of the public defaults.

Shared diffs live in `timeline.diff`; selected-source-range conversion lives in
`timeline.cutting_contracts`. Best-effort duration and exact selected-stream rate
probes live in the FFprobe adapter. Validator lookup lives in `avo.paths` and
keeps its distinct missing-file fallback. Pure Shorts rules and SFX metadata
live in `avo.shorts_rules`, re-exported by `shorts_media` for existing callers.

Pattern decision: ordinary functions for shared rules and explicit injection at
tool boundaries. No new Strategy, Facade, base-service hierarchy or dependency.
The shared diff separates item changes from ordering changes and passes the
existing complexity ceiling without an exception; the two former CMap/BMap
diff exceptions are removed from the quality allowlist.

Validation: characterization of serialized diffs, probe failures/stream
selection, native sample-rate caching, legacy defaults, Shorts mappings and
config fallbacks; core/unit tests; import contracts and the repository quality
gates. No changes to editorial selection, audio processing or render settings.

Verification on 2026-10-10: core suite 1,747 passed / 24 skipped; unit coverage
71.31% (1,633 passed / 3 skipped); 15 new tests passed through the npm entry
point; 1,000 differential CMap/BMap cases matched the previous implementation.
All five import contracts and the quality gates passed. Remaining gates were
rerun with Windows-trusted certificates after a PyPI trust-chain failure;
certificate verification stayed enabled and no dependency manifests changed.

See [software foundation](docs/software-foundation.md),
[engine ownership](docs/engine-vs-orchestrator.md) and
[software quality](docs/software-quality-audit.md).

## Quality evidence boundary

Quality and mutation jobs remain independent measurement producers under
`scripts/ci/`. The always-run readiness check evaluates mandatory job results;
the report collector waits for that result and joins artifacts from the same
commit and workflow run. One normalized dashboard series feeds the text table,
PNG metadata, and schema 2 release snapshot. Rendering and image hosting are
optional presentation steps; they cannot substitute for successful checks or
complete mutation accounting.

Schema 2 freezes the mutation profile/floor and records job results. Current
release cuts validate commit/run identity, complete mandatory measurements, successful
readiness, and image/data equality. Historical schema 1 readouts remain
decodable, but cannot satisfy a current run-bound cut. No AVO engine, CLI, MCP,
media contract, or footage-project dependency is introduced by reporting.

The scheduled safety branch report and package dependency table are diagnostic
outputs. They do not change existing PR floors or import contracts. Validation
covers malformed counts, incomplete/stale evidence, skipped and failed jobs,
legacy snapshots, chart equality, import resolution, and safety rejection paths.
See [quality reporting](docs/quality-reporting.md).

Measured values, gate decisions, and required-job results have distinct readouts.
Capture receipts bind actual commands and output hashes to the commit/run and
source fingerprints. The report revalidates downloaded inputs and uses the same
normalized observations for tables, PNG metadata and release snapshots.
Informational function CRAP uses exact statement coverage and Radon complexity;
static package CA/CE retains its original projection. JUnit testcase-event counts remain execution
evidence. Unmatched inputs stay unmeasured, and these diagnostic metrics do not
introduce new enforcement thresholds.

CI report publication stores the dashboard PNG and normalized JSON in Actions
artifacts and links those exact-run downloads from a comment per current PR run.
`link_quality_artifacts.py` only rewrites local report text; it has no network
or Git write path. The report job uses read-only repository contents permission.
Missing uploads preserve the text evidence, and deliberate release snapshots
retain their existing identity and image/data validation.

Feature 010 adds an optional reporting context and verified supporting observations
inside the existing schema 2 artifact. Dependency direction remains producers
and capture receipts -> `quality_measurements.py` -> frozen view series ->
text/index/PNG renderers -> offline linker -> guarded publisher. The module
graph is separate from the package projection: real files retain exact static
degrees, namespace targets are not file points, and same-package imports remain
visible. Function records reconcile source identity, CC and same-function line
coverage before CRAP can be measured. Invalid or unknown population stays explicit.

`coupling_dashboard.py` and `quality_hotspots.py` consume frozen verified data;
they never reread source or rerun analyzers. Full Markdown/JSON indexes precede
optional PNGs, with deterministic file/group/function IDs and identical embedded
series. Reference medians, disclosed piecewise log spacing and CRAP 30 are descriptive diagnostics,
not gate policy. Primary chart rendering and dashboard-only release requirements
remain compatible. Live supporting presentation requires owner preview approval.

The code-backed metric-definition catalog is independent of reviewed test
baselines. Reports freeze semantic revisions, catalog/policy hashes and a
measured-commit reference; historical series retain their original interpretation.
Ordinary unit verification runs fixed independent behavior cases without writing
baselines. Producer, policy and analyzer changes require an explicit reviewed
semantic diff, separate from changing live measurements.

New PR runs receive distinct run-keyed comments; retries update only their own.
Freshness and cancellation guards precede publication, with exact head/base/tested
identities explaining any historical in-flight result. A fatal builder failure
uses a standard-library Markdown-only path and restores the original job failure
after delivery. Native images are restricted to five fixed roles, independently
validated against current-run frozen data. No reporting path creates Git commits,
branches, tags, public engine interfaces or new credentials. Verification covers
source/receipt corruption, unknown states, definition drift, frozen history,
image failures, optional roles and PR freshness; live delivery is verified only
after approved publication. See [quality reporting](docs/quality-reporting.md).

The mutation job additionally retains per-source mutmut outcomes and exact raw
metadata, without another mutation execution. `mutation_scopes.py` validates
active-profile membership and complete outcome accounting; the report collector
rechecks retained hashes, aggregate reconciliation and available source hashes.
`quality_mutation_dashboard.py` consumes that normalized evidence and keeps the
existing profile floor aggregate-only. `quality_gate_decisions.py` renders
categorical decisions, policy and execution proof separately from measurements
and required jobs. Both views have complete Markdown/JSON indexes, independent
image fallbacks and definition/fixed-case baselines. Historical catalogs retain
their original optional view set; release validation still requires only the
dashboard image. No public product or measurement gate changes are introduced.

## Evolution: final-master detection (2026-10-15)

`avo.master_artifacts` owns the shared metadata-only final-export locator used
by project inventory, reconstruction and duration statistics. Legacy
`edit/masters` lookup remains compatible; an explicit delivery-manifest reference
can locate an existing export elsewhere inside the footage project when its
identity agrees with the final transcript. No export is moved or copied, and
the locator does not confer approval or replace reconstruction's byte checks.
The module uses only the standard library, with no CLI or adapter dependency.
Validation covers legacy lookup, documented exports, unsafe or ambiguous
references, source-bound transcripts and the independent reconstruction gates.
See [cleanup safety](docs/cleanup-safety.md).

Reconstruction distinguishes media-owning indexes from archival iteration
history using the validated index's `artifactType`. Only CMap, BMap, Tracks,
Animation and Sync contribute current media fingerprint constraints. The ledger
and all of its revisions/events remain archived unchanged, while review
authoring documents are preserved under their current byte identities. The
shared scanner enforces this boundary during both bundle construction and
coverage verification; historical request versions cannot invalidate one another
or weaken current media checks. Regression coverage includes conflicting
historical references, archive integrity and all five current-media index types.

## Evolution: existing-master adoption and preservation closure (2026-10-16)

Timeline delivery can adopt an existing project-local master using current
canonical assembly, native candidate, real review and existing transcript
sidecars. Adoption performs validation and metadata registration; it does not
call rendering, copying or ASR services. The normal delivery-preparation route
is unchanged. Candidate transcription has an explicit reuse-only mode that
fails closed instead of starting ASR. Native Watch hashes large candidates by
streaming through the shared fingerprint function rather than loading the whole
export into memory.

Visual frame acquisition batches the sorted unique frame indexes into one
FFmpeg selection pass. A bounded standard-library PNG reader validates framing,
dimensions and CRCs before mapping outputs to those indexes. Existing caches
must equal freshly decoded bytes and are rechecked before inference. Tiny CFR
and VFR parity tests verify equality with the original exact-frame extractor;
malformed streams, excess/missing images and cache tampering fail closed.

The QC registry can explicitly collect the union of motion, pre-master and
delivery evidence. Timeline approval validates the exact candidate, frozen
regression contract, artifacts and structured visual coverage; historical
creator acceptance remains a separately fingerprinted input. A single explicit
administrative adoption event preserves old pipeline history, rather than
fabricating sequential gate approvals. Normal lifecycle guards are unchanged.
Assembly QC validates its persisted canonical graph and fidelity contract
directly, without requiring the legacy projection format.

Project inventory owns distinct preservation evidence: exact reconstruction
verification plus zero-candidate scanning, explicit whole-edit retention and a
retained metadata snapshot. Wrap can finalize from this in-process verified
result or revalidate a persisted receipt. Preservation is separate from cleanup
execution and records null freed space. It cannot create a cleanup receipt or
inherit an unverified dry-run pass. Output path guards prevent redirection through
links or reparse points. Dependencies retain their existing direction:
timeline delivery uses approval/contracts; wrap uses inventory; neither delegates
trust decisions to documentary reports. Tests cover stale identities, incomplete
gates, forbidden ASR/copy paths, retention scope, receipt tampering and unchanged
legacy routes. See [adoption](docs/native-master-adoption.md) and
[cleanup safety](docs/cleanup-safety.md).

An explicit human-final disposition is a separate authority path for adopting
an already reviewed master. The current creator instruction, exact candidate,
canonical owners, frozen plan, prior acceptance and original automated evidence
are fingerprinted together. Failed or interrupted automatic judgments remain
unchanged; human acceptance is never serialized as an AI pass or a successful
regression. Strict automatic approval remains the default. Human authority does
not replace byte identity, source lineage or transcript provenance checks.

Human-final delivery and administrative archive events retain the historical
candidate references and identify the final master directly. Administrative
archive records the creator's whole-project retention decision; actual byte
verification is recorded separately in the final preservation receipt. All
native mutations precede the final reconstruction build and preservation
verification, so the archive event cannot stale the receipt. Wrap sidecars are
administrative outputs rather than reconstruction inputs. The verifier reuses
only fingerprints computed during its own current loop; no persistent cache
or historical hash substitutes for fresh verification. See
[preservation closure](docs/preservation-closure.md).

## Evolution: single-pass cleanup verification (2026-10-16)

Canonical cleanup verifies reconstruction bytes and dependency coverage once per
`run_cleanup` call. The inventory service retains that freshly verified protected
set inside the same invocation for presence checks, candidate scanning and native
deletion. It accepts no external cached pass. Independent inventory and verify
commands retain their own validation, and legacy reconstruction promotion is
unchanged. Missing or changed dependencies still block before deletion; the native
receipt records intent first and counts only files actually absent afterward.

## Provider artistic direction and Briefstart (feature 009)

`avo.direction` is an additive authorial-guidance module. Dependency direction is CLI/MCP and pipeline coordinator -> direction services -> bounded normalized documents, strict shared contracts and immutable/index-last storage. It does not depend on video adapters, renderers, transcription, Watch, model runtimes or media decoders. The driving agent authors semantic conclusions using an exact prepared packet; native Python validates evidence, support scope, references, provenance, word budgets and explicit creator decisions. It never infers hidden artistic intent from technical measurements.

Provider storage lives under `providers/<slug>/direction`; per-video intake, proposals, decisions, frozen source snapshots and optional offered-to-authoring receipts live under external `<rawDir>/edit/briefstart`. Each has one validated mutable index, immutable bodies and exact SHA-256 references. No active brief pointer is copied into `pipeline-run.json`. `TimelinePipeline.status` derives `briefing.stageContexts` for structure, CMap, BMap, motion and sound from the selected index and current canonical head hashes. Those are guidance offers, not evidence of implementation, cut/render approval or media-reuse permission. Installed stage instructions consume them before style-dependent proposals.

A raw start remains valid. Built-in directions are four packaged versioned JSON resources. An exact accepted provider version or inspected/user-described reference descriptors can be chosen; explicit new choices remain reviewable proposals. Bound videos replay locally frozen authorial sources, even if the provider is offline or later changes. Refresh, edits and qualifications create new reviewable versions and retain lineage; rejection/defer records remain visible. Current creator instructions and integrity, meaning, accessibility and rights rules take precedence. Ordinary project/master approval does not become provider-wide creative authority.

Document reads are capped at 2 MiB, source collections at 16 MiB, prepared agent packets at 24,000 words, complete short option views at 600 visible words. Continuations and derivatives are not independent recurrence votes. Unavailable, changed, oversized or unknown historical evidence is labeled rather than fabricated. Evidence/descriptors are data, never executable instructions or fetch authorization. Optional historical-learning diagnostics may warn with unknown counts; explicit strict readers and required current source/proof gates remain blocking.

Publication uses per-resource exclusive locks, compare-and-swap and an index commit last. An orphan body cannot select a direction. Committed request-result snapshots permit exact replay without reverting today's index. Recovery requires explicit authorization and proof that the same local recorded process is absent; Windows liveness checks are query-only. Service retries reuse only fully matching verified envelopes apart from generated timestamp/hash fields. Immutable body tampering or conflicting request identity fails closed.

The canonical Draft 2020-12 schemas ship with the Python distribution at `share/avo/schemas` and the binary bundle. Checkout/bundle schema lookup remains preferred. Schema meta-validator compilation is cached by complete schema bytes only; instance validation, source-byte freshness, document hashes and current decisions are rechecked. No source or approval cache is keyed only by size/mtime. Built-in resources ship through Python package data and the binary manifest. The installer copies the same skill reference tree; public engine `direction` and `briefstart` aliases route to the shared native CLI.

Compatibility exceptions are explicit: optional authorial context adds no lifecycle state or mandatory creative gate; old videos/declarations remain valid; historical proofs are references only. Reconstruction retention explicitly includes briefing authoring/state documents without retaining whole provider history or opening historical media locators. MCP bridges share native handlers; exact creator decisions use existing consent with a bounded decision-document digest, preventing approval of a different file body at the same path.

Validation includes neutral contract/service tests, real coordinator handoffs, frozen offline replay, source/brand changes with unchanged metadata, crash/retry/CAS/lock cases, descriptor safety, actual isolated skill copying and installed distribution smoke. Provider pilot source coverage, human classification, exact profile acceptance and observed usability timing are reported separately; automated success is never substituted for human results. See [provider direction](docs/provider-direction.md) and [pilot protocol](docs/provider-direction-evaluation.md).

## Video cost accounting (feature 011)

Implemented by the [feature 011 plan](specs/011-video-cost-transparency/plan.md):
local metadata accounting outside editorial timeline authority. Pure
normalization/pricing/aggregation functions consume versioned source-reader
output; CLI, skills, wrap/export and optional MCP use the same accounting
service. Source readers and filesystem persistence depend on the accounting
contracts, while accounting rules do not depend on agent SDKs or model calls.

Immutable usage batches and snapshots live in the footage project's
`edit/costs/`, preserved by canonical and legacy cleanup. Channel provider and
AI service provider are separate identities. Each observation retains its
actual model/service/billing basis through switches. Existing timeline and
session IDs remain aliases; an accounting UUID prevents master-name changes
from splitting video history. Legacy wraps without costs stay readable.

Learndown and verified cleanup responses automatically display draft/final
snapshots with coverage and cutoff; production completion does not imply an
exact invoice or a fully reported closing turn. Validation must prove
deduplication, category overlap, switching, cleanup preservation, portable
history, privacy and same-snapshot agreement across response/wrap/export.
`costs_cli` and optional MCP call `cost_store`, `cost_sources`, `costs` and
`cost_history`; wrap/export call `cost_closure`. `cost_services` captures only
available response usage from AVO-owned review/probe calls. None of these
modules selects media or changes editorial approvals. History reads declared
`.avo/cost-locators` and provider exports, independent of bounded session stats.

Immutable publication uses an exclusive per-document directory lock, an fsynced
same-directory temporary file and atomic replacement. Interrupted locks fail
closed and require explicit recovery. Batches freeze tariff references and
precompute observation keys; reports verify batch integrity and capture one
membership set. Snapshots retain that exact set. Conflicts need an explicit
selection/exclusion; revaluation appends evidence and preserves old snapshots.
Portable exports preserve document IDs, including snapshot drill-down paths.

Compatibility is additive: legacy videos remain readable with unknown costs,
manual/normalized evidence works for every installer agent, and documented
local import shapes are offered only for Codex exec, OpenCode exports and
projected Claude/Gemini metadata. Interactive/Desktop log formats are not
guessed. Imported evidence cannot establish account-wide completeness; current
coverage remains partial or not-recorded, even after production is finished.

Regression tests cover source isolation, source intervals across three videos,
model/provider switches, counters and rollups, incomplete pricing dimensions,
atomic-write failure, identity races, immutable export/history, cleanup retention,
private-field rejection, engine/MCP routing and automatic response instructions.
The dedicated 100,000-observation benchmark passes the five-second report target.
See [cost transparency](docs/video-cost-transparency.md) and the
[validation record](specs/011-video-cost-transparency/quickstart.md).

