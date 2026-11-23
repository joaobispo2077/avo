# AVO architecture

Native Shorts delivery lookup is shared by inventory and reconstruction through
`avo.master_artifacts`. It consumes batch manifest item records and resolves their
JSON sidecars without relocating media or creating approval. Legacy individual
master lookup remains supported. Project-boundary checks and exact transcript
source identity precede independent byte verification by reconstruction. Regression
coverage lives in `tests/test_master_artifacts.py`.

AVO is a local-first modular monolith. `src/avo/` contains the bundled editing
engine and application orchestration; CLI and MCP expose the same operations.
Hexagonal architecture applies at real external-tool boundaries, not through a
mandatory domain/application/infrastructure directory template.

`AGENTS.md` remains the canonical agent instruction file. This document records
architecture and its evolution. Every architectural evolution must update this
root document with its responsibility, dependencies, compatibility and checks.

## Resolve export inspection

`avo.timeline.otio_import` performs bounded structural inventory of standalone
OTIO JSON without importing native OTIO packages, accessing referenced media or
mutating a timeline. `avo.timeline_import_cli` exposes the core CLI command;
it is not a new `/avo.*` surface and therefore does not add a separate slash
command registry owner. Canonical provider/pipeline ownership remains unchanged.
Reports explicitly leave semantic, source, sync and render readiness unchecked.
Clip schema versions and active media references are preserved as diagnostic
facts. Unknown schemas and export omissions do not acquire render authority.
Tests: `tests/test_otio_import.py` and `tests/test_timeline_import_cli.py`.
This diagnostic boundary remains independent of canonical reconstruction and
the optional reader. It cannot select an edit or import historical approval.

`avo.timeline.import_service` stages exact export bytes and version-bound
evidence in external `edit/timeline/imports/<importId>/`. CLI injects the pinned,
isolated OTIO core reader and existing FFprobe inventory port. Native placements
are checked against exact raw clocks; unknown treatment and unsupported layout
block the whole experimental contiguous import. Source identity, explicit
routing, current approved source-bound Sync/N/A, expected head and current
project/provider configuration are locked before one CMap draft is selected.
The canonical CMap's strict `originRef` is the sole import-selection authority;
packet state is recoverable bookkeeping. No finishing head or approval is
inherited. Existing slash command ownership remains unchanged.

Timeline store mutations, source-authoring services and lifecycle mutations use
one reentrant kernel writer per timeline. Explicit `empty` head expectations are
distinct from legacy omitted expectations. Persistent lock files survive cleanup;
POSIX fork handling closes inherited descriptors without unlocking the parent.
Activation journals deterministic revision identity and blocks ordinary mutation
and rendering until interrupted selection has reconciled. Current Windows tests
cover separate-process collisions and before/after-commit retries; POSIX-specific
fork qualification is skipped on Windows.

The optional `preserve-import` source policy is bound into canonical revision and
ProofPlan identity. Source-only cut graphs must match the canonical reconstruction
at compile and preflight. The native executor preserves explicit channels and
sample trims without implicit fades/restoration. Audio is decoded from its origin
to avoid container timestamp-seek rounding; a later fingerprint-bound seek index
may improve long-source throughput. Ordinary snapshots retain their prior audio
policy. Synthetic native tests compare every decoded picture frame and PCM
sample, including a scoped trim/restart. Real Resolve exports, human reviews,
and packaged runtimes remain separate qualification work.

Placed imports use a mutually exclusive `layoutMode=placed` CMap instead of
segments. `import_layout` validates half-open source/program clocks, explicit
program duration, ordered tracks, occurrence identities, gaps and audio routing.
Mapping requires a placement/track selector when a single result is ambiguous.
Legacy snapshots and their endpoint behavior remain compatible; legacy EDL and
automated cutting consumers reject placed content instead of flattening it.
CMap diffs account for sources, placements, tracks, gaps and output settings.
The CMap Sync reference accepts the existing canonical revision-basis form as
well as the legacy dependency form; this fixes their previously mismatched wire
representations without discarding either existing shape.

`initial_cut_placed` compiles one genuine `source-layout` picture operation and
independent sample-addressed source audio. The native `proof_placed` adapter
admits original media through shared fingerprint/stream checks, builds finite
source trims, composites over explicit black, and uses the existing continuous
PCM mixer without a sequential-dialogue lead. The final encode stays shared.
Still verification is injected into import orchestration from the CLI and is
repeated by native execution; supported images are single-frame and literal,
never expanded as sequences. Known non-square pixels and unsupported timing or
treatment block this capability. The optional native reader remains isolated.

Later checkpoints may append admitted `overlay-video` operations to the unique
imported source-layout base. The base keeps its original placements, privacy
masks and continuous source-audio graph; added audio remains explicit mixer
nodes. Generated overlays use the existing compositor and fresh closing guard.
Microproofs count only emitted overlay inputs when routing the final audio,
including windows where every overlay is inactive. Cut-proof still requires the
exact source-only canonical reconstruction.

Microproof and full proof use the same graph. Both preflight/render paths close
a fresh fingerprint-verification batch before publishing evidence, including
retained inactive originals. Ephemeral same-plan media owns a separate fingerprint
stage and cannot become a dependency of a later proof. Native implementation
digests include the placed compiler, clock/layout validation, renderer and still
admission helper. New interpreter identity 2.0.0 prevents silent reinterpretation
of older staged packets. Native tests cover exact picture/PCM, layer gaps,
static alpha, independent audio, scoped occurrence edits, restart and mutation.

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
- Python 3.11 is the minimum supported version. No new package dependency is required here.

## Proof input verification

The native FFmpeg proof executor compares every operation's source lock during
execution. Ordinary renders hash each resolved source path once per input-check
phase. Contextual preview windows may share that observation within their
explicit batch, which rehashes all originals before the preview manifest is
written. A new ordinary render or batch starts fresh, conflicting claims still
fail, and generated-asset validation stays independent. This removes duplicate
raw-file reads without changing media selection, processing, or approval rules.
Regression coverage: `tests/test_proof_input_revalidation.py` and the FFmpeg and
code-drawn executor integration suites.

## Cutting evidence validation

Nested original-source ranges are validated once per distinct canonical JSON
value within one cutting-document validation. Repeated acoustic evidence can
reference the same speech interval many times; reusing that successful check
does not alter the stored document or its hash. Changed ranges, invalid clock
types and empty intervals still fail the existing validator. Each new document
validation starts with an empty set, so no cross-document validation result is
trusted. Regression coverage: `tests/test_cutting_contracts.py`, cutting-store
and cutting-service tests.

Native boundary verification shares original-source fingerprint observations
only for one verification invocation or one enclosing preview-package check.
Every extraction still compares its own expected fingerprint, rate, routing and
sample coverage. Successful batches rehash every observed source before any
result returns; a changed source blocks the batch, and the scope is reset on
success or failure. Identical signal windows share one physical comparison
within that invocation while retaining each required occurrence ID. Any changed
window input is checked separately. Rendering and observation generation retain
their independent source checks outside the explicit preview-package batch.
Within that batch, before/after renderer source checks use the same observation
and the enclosing batch rehashes originals before returning. Generated media
fingerprinting is never cached. Regression coverage:
`tests/test_cutting_verification_reuse.py` plus native preview and word-edge
integration suites.

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
# Shorts source-fidelity composition

The native Shorts plan can drive a specialized registered source-fidelity
renderer: original picture and finite inserts remain in FFmpeg at 10 bits,
while the recorded engine supplies admitted graphics alpha only. Dialogue restoration precedes
the independent PCM effects mix. Timing and source identity remain owned by the
resolved plan; generated HTML and prior exports carry no editorial authority.
The specialized Shorts path retains its source-fidelity contract. The canonical ProofPlan executor also supports admitted generated bases and alpha overlays through its separate frozen graph. Contracts,
compatibility limits and validation are documented in
[Timed Shorts inserts and source fidelity](docs/shorts-timed-inserts-source-fidelity.md).

# Shorts v1.2 audio treatment and beds

Shorts request v1.2 adds declarative dialogue treatment and rights-bound audio
beds without changing the timeline owner. Planning validates and fingerprints
the selected source, treatment settings, and authorized bed window before any
media work. Media preparation produces treated dialogue plus untreated and
removed-signal review assets; final composition orders dialogue EQ, restoration
and loudness before independently mixed music or generated SFX. Only the
candidate that resolves an `audioBedOverride` receives that bed.

Requests from v1.0 and v1.1 remain readable with their historical behavior and
must not silently gain v1.2 audio fields. Missing provenance, changed bed bytes,
out-of-window use, or mismatched lineage fails closed. Review stems are audit
artifacts and cannot become picture or delivery ancestors. Proof approval,
music/rights approval, and master promotion remain separate human gates.

## Video cost accounting (features 011 and 015)

[Feature 011](specs/011-video-cost-transparency/plan.md) and
[feature 015](specs/015-agent-cost-continuity/plan.md) provide local metadata
accounting outside editorial timeline authority. CLI, installed engine, skills,
wrap/learndown and optional local-stdio MCP use the same services. Accounting
never selects footage, changes editorial approvals or starts inference/rendering.

`cost_store` owns contained immutable publication, schema/version dispatch,
source/evidence references, captured membership, snapshots and portable readers.
`cost_sources` owns explicitly authorized bounded readers and version-qualified
projections; `cost_profiles` freezes parser/fixture/temporal/category/tree proof.
`cost_participation` validates lifecycle/decision DAGs, separates responsibility
intervals from source grants and implements context/transition/reconciliation.
`cost_estimates` processes explicit manual ranges or supplied visible text with
installed pinned local tokenizer assets, retaining safe metadata only. `costs`
normalizes accepted representations and Decimal financial views from one capture;
`cost_closure` coordinates verified closure and mutation-only recovery. Domain
rules do not depend on vendor SDKs, a daemon, remote telemetry or MCP registration.

Canonical identity and evidence live in `<rawDir>/edit/costs/`, retained by normal
cleanup. Editorial provider, inference provider, product/surface, served model,
billing mode and agent role remain distinct. Production UUID survives rename;
runs/devices/sessions are aliases. Missing current context records an expected
unknown executor, never the prior active host. Selected-model hints do not
rewrite historical served-model evidence. AVO-owned response usage is captured
by `cost_services`; host-native capture requires its own admitted profile/source.
No bundled vendor host profile is currently qualified; nine named environments
plus an unknown route have explicit candidate/manual/unavailable fallbacks.

V2 batches atomically publish unchanged observation payloads, separately hashed
evidence and receipts, including receipt-only or metadata-only commits. Frozen
profiles, participation facts, estimates, reconciliations, bindings, prices and
corrections all enter capture/integrity/export membership. Source collection is
bounded to 8 MiB/10,000 records per call and 1 MiB per record; typed/manual inputs
remain capped at 32 MiB/100,000 observations. Native IDs/epochs/baselines and
explicit boundaries govern attribution; counts or timestamps never establish
identity, copied-history ownership or a guessed proportional split.

Publication uses exclusive directory locks, fsynced same-directory temporary
files and atomic replacement. Per-operation replay checks, reconciliation-family
serialization and explicit local activity claims prevent conflicting concurrent
publication and double allocation. Audited transfer chains/reversals preserve
all records; contradictory choices remain conflicts. Local source locators are
explicit discovery hints, not portable access grants. No multi-host/cloud-sync
merge guarantee is implied.

Evidence quality, acquisition and financial basis are independent. Measured,
manual and legacy-unknown accepted counts remain visible; modeled usage and
overlap conflicts are separate. Reported charges, tariff estimates, API reference
equivalents and manual allocations group by unit/basis, never as one invoice.
Prices freeze at admission; unknown model/rate/currency interpretation does not
erase known counts/charges. Subscription percentages/credits have no universal
conversion, and local inference does not imply zero hardware cost.

Closure completeness requires every expected responsibility interval, qualified
source semantics, applicable counter baseline, exact accepted frontier and linked
terminal flush, with no unresolved coverage gaps. V2 pending states map to
true/true/null/false for open/settling/unknown/none. Reports/history never collect
or repair; committed late data is disclosed as stale. Authorized mutation/replay
repairs a linked amendment while retaining exact old closures. Wrap, learndown,
history and current reports share captured values before rounding.

V1 payloads/IDs/hash rules and exact snapshot lookup remain intact. Current v2
views expose historical evidence as legacy-unknown, without mass migration or
retroactive completeness. Unsupported major schemas fail closed. A format
marker cannot force an unmodified old executable to honor v2, so one compatible
writer runtime is required. Portable projections retain safe accounting values,
original digests and explicit omitted-preimage/replay limits; they never present
redacted data as original verified bytes, and collection needs reauthorization.

Regression proof covers context/lifecycle transports, manual bootstrap, source
versions/bounds, three-agent/four-model resumes, child/aggregate overlap,
metadata correction/withdrawal, exact-scope estimates, concurrent ownership,
privacy, canonical cleanup retention, immutable closures and portable history.
Synthetic acceptance includes privacy, immutable closure recovery, portable
replay and all-family retention through normal cleanup after temporary source
removal. The integrated accounting/public-surface suite passes 506 tests;
architecture, dead-code and duplication gates pass. Existing unrelated
complexity and dependency-audit failures are recorded in the validation guide.
Corrected external-root rechecks resolve library/media fixture-harness failures;
combined same-revision coverage is 78.20% against the 68% floor. The existing
complexity contract still fails and repeats in the completed serial-unit run.
The last quiet 100k report measured 5.906732s and failed the original `<5s`
requirement. On 2026-11-01 the user approved retaining the complete auditable
report with a scoped `<7s` H: reference-machine cap. The first fresh attempt
measured 7.726554s and failed; host background CPU remained elevated after team
tests exited. Idle-qualified verification is pending, the failed sample is
preserved and the approved cap is unchanged. This is not a NAS/CI or
other-machine latency guarantee.
The feature-011 benchmark is a historical reference only.
On 2026-11-01 the user accepted delivery with T056 performance verification
deferred; the seven-second cap and failed samples remain unchanged, with no
active benchmark or idle monitoring.
See [agent cost continuity](docs/agent-cost-continuity.md),
[cost transparency](docs/video-cost-transparency.md) and the
[feature-015 validation guide](specs/015-agent-cost-continuity/quickstart.md).


## Optional ArtCraft provider authoring

The ArtCraft assessment receives a closed request and the current invocation's
intent separately. It resolves existing routes and pinned component evidence
against the exact provider, component and required behavior. CLI and MCP share
this assessment and the bundled capability catalog. An eligible decision
records one app and its operations. The authoring boundary re-evaluates that
same scope before tool access. Motion engine selection and canonical timeline
ownership stay with the existing services.

Provider job records live in a declared external workspace. The shared
ArtCraft schema and timeline store primitives bind job and event content,
serialize writes and compare the expected event head. An exact operation can
recover after an interrupted index write. App observations, reusable source
receipts and creator decisions carry distinct evidence. Legacy component
commands reserve ArtCraft declarations for its qualified admission path.
Packages include the AVO-owned catalog and schema. Users manage the selected
app installation separately. The distribution smoke reads bundled metadata.

Structured ArtCraft job tools invoke the same prepare, run, inspect and recover
commands as the CLI. Inspection and recovery compare the selected event head
with current evidence and read only the artifacts owned by the job. Recovery
reports a next action and fingerprints bounded partial files for reference.
Preparation checks the combined input file and byte counts before app
discovery. The run checks its retained output counts and elapsed time before
publishing an export, including copy-only reuse. Late or oversized results
enter reconciliation with their bounded recoverable files.
The shared specialist CLI runner checks each reply before scanning scratch.
It stops the scan at the first exceeded file, byte, or time limit.
An interrupted write retains its event and requires a fresh job before another
attempt at authoring.

The first AniCraft profile authors a Windows 0.2.1 lower third from a job-owned
empty document. A supplied confined command runner executes the fixed native
recipe and checks the exact saved stage and clock, installed font family and
fresh-session pixels. The renderer reconstructs straight alpha from two native
backings and verifies every channel against an independent third. Job events
bind the saved native source, recipe and frame fingerprints. The guided route
prepares the same native recipe under operator control and retains its returned
files as references. Proof admission remains a separate decision boundary.

An explicit host-MCP job stages a headless AniCraft launch descriptor and a
version-specific operator recipe. It binds the installed files, owned empty
document, command IDs, permitted roots and resource limits. The handoff requires
the selected host to enforce those limits. AVO stages and inspects the handoff
without connecting to the host or starting a server.

AniCraft JSON-lines authoring uses an independently confined stdio runner and
the same fixed recipe and verification as CLI batching. It checks the startup
record and waits for the exact successful receipt at each step before sending
the next command. The first failed or incomplete receipt leaves a recoverable
job outcome and prevents subsequent commands.

The qualified Windows AniCraft 0.2.1 JSON-lines lower-third export can enter
the same proof binding and exact copy-only reuse paths as CLI batching. The
binding still requires current app and CLI fingerprints, the retained recipe,
and the exact video placement and timeline revisions.

The explicitly selected SoundCraft cue profile accepts one external WAV and
an exact 48 kHz stereo output contract. A confined Windows 0.20.1 CLI builds
an owned session with one track and the built-in room reverb. The media
adapter independently decodes the retained source and both bounces, checks
the PCM clock, and compares the saved session's fresh bounce. The export event
binds the editable session, recipe, retained audio dependency and decoded
output for standalone review. Canonical proof admission has its own checks.

Generated cue placement binds the export receipt and output fingerprint to an
explicit SFX region in Tracks. Proof compilation seals both identities and
verifies the current frame and sample ranges. Materialization and native
execution recheck the receipt and its closure while resolving the audio.
The native mixer adds the cue through the existing SFX node and final encode.

Generated ArtCraft cues and stills use their recorded provider and video scope
at Tracks authoring and proof compilation. A video-scoped receipt must match
the exact project, video identity and raw workspace. Provider-level receipts
can serve multiple videos within that provider. Static-card admission verifies
the PNG representation of the selected source.

ArtCraft proof admission and vector handoff recheck the exact installed
application and CLI fingerprints from the selected job. This file validation
is independent of command registry discovery and follows the retained artwork
dependency when an animation uses it.

The selected VectorCraft Windows 0.24.1 profile stages a fixed card recipe
under a confined runner with plug-ins and preferences disabled. It retains
the editable native source, its bounded inline resource envelope and the
verified sRGB RGBA still. Tracks selects that exact static asset and its
placement. Proof execution verifies the source, dimensions and decoded pixels
before using the existing overlay layers for the exact requested frames.

The selected VectorCraft emblem and AniCraft motion profiles run as explicit
jobs. AniCraft accepts one exact same-provider, same-component emblem export.
The motion job binds the upstream job head, editable source, recipe and SVG.
It imports a bounded inline polygon, preserves it as an editable symbol, and
verifies its reopened alpha frames. Proof admission rechecks that dependency
through the existing generated-asset binding. Optional sound enters through its
own SFX region on the same canonical timeline.

The optional AniCraft lower-third identity mark uses the same verified
VectorCraft receipt. Its inline shape and readable text width are checked in
the native source. Saved-source text edits and copy-only reuse retain the exact
artwork closure. Switching that artwork requires a fresh render and proof.
Copy-only reuse also retains the selected predecessor's job and event journal,
editable export, recipe and frames. Inspection and reconstruction recheck the
recorded fingerprints. Any change requires a new verified export before reuse.
Reconstruction matches linked VectorCraft artwork to its selected export and
checks its bytes against the video's retained proof and preview inventory.
Video-local native packages reapply the published source-role checks when
reconstruction reads them. Unsupported plug-ins block that reconstruction.
Native provider publication can retain that SVG as optional identity artwork.
The package validator binds it to the exact native shape, design review and
per-file rights before the package and video instance retain its bytes.
An explicit instance ID and hash can bind a saved-source label job to that
video-local package. The job verifies the selected original, parameters,
output contract, artwork and rights through the existing input closure.
An optional kit sound binding pins a generated SFX region on the active
Tracks revision. Video proof admission checks its BMap cue and timing.
An explicit registration selector can bind a plain kit through the same
verified native source and immutable instance. Tracks owns the mix.

The selected FilmCraft Windows 0.20.1 profile saves and reopens a native
project and exports an OTIO timeline linked to the exact original. AVO checks
the application version resource without starting the desktop editor. The
import service verifies the retained exchange and original fingerprint before
mapping relative references. The existing import, sync and approval workflow
owns any later activation. Declared exchange losses, unsupported treatments
and prohibited original ancestry leave the return as reference material.
Before staging a FilmCraft return, the import service can compare the original's
compressed picture stream with retained local outputs through the media probe.
It uses the selected job's time budget and reports matching streams across
containers as prohibited ancestry.

The explicitly selected video export binds the unchanged AniCraft source,
recipe, app and CLI fingerprints, ordered alpha frames and current approved
cut and sync to the logical component in Animation, BMap and Tracks. Proof
composition observes the actual source and packs the frames into a silent
lossless FFV1/BGRA clip. It checks each decoded frame and timestamp before
registering the generated asset. The timeline service verifies the retained
binding and recursively rejects forbidden output ancestry. Compilation and
execution read the same source lock and use the existing `overlay-video`
operation, preserving the canonical placement, alpha and local frame phase
through full and window proofs. Creator review follows the existing gates.

ArtCraft review pairs the retained standalone phase frames with an exact
original-footage candidate when the caller selects its proof record. The
review reader verifies the immutable plan, materialization, source binding
and current candidate bytes, and links available source and edit logs. It
reports the review as pending for the existing creator approval workflow.

ArtCraft job recovery resolves an exact retry through its prepared, run and
result events. A completed retry rereads the saved source and verified export.
An interrupted write retains bounded file fingerprints as reference material.
Cancellation of an unstarted job uses the same event compare-and-swap and
preserves the source copy. Owner reconciliation is required for active work.

An active CLI job can be cancelled when its confined runner claims the exact
job, running event and output directory. AVO records the request before
signalling and keeps partial files as reference evidence. A cancelled event
requires a settled runner and writes. Concurrent retries reuse the recorded
request or result. Operator-owned and unverified writers retain their current
state.

The ArtCraft inspection response lists changed recorded files and the review
actions for each affected area. A checked AniCraft lower-third document also
reports differences in its editable text and font. These observations leave
the existing job and creator decision records intact.

Reconstruction retains native job journals, declared editable sources, recipes,
and selected ArtCraft exports. It follows generated Track references and the
selected artwork dependency. Video-local provider packages retain their exact
manifest, rights and review files. A bundle records the fingerprints of selected
ArtCraft inputs outside the raw workspace. The installed editor can rebuild from
the retained native source after the temporary render backing is discarded.

Cleanup verifies shared ArtCraft package versions within the selected edit tree
and includes their manifests and declared files in the preservation set. The
same cleanup check protects a package owned by a different provider. Native
publication staging stays protected while the package writer owns it.

PhotoCraft's selected layered image card uses a separately installed Windows
0.23.1 CLI through the confined-runner port. The native package embeds the
original raster and ICC profile separately from its editable Curves layer. The
adapter checks the embedded asset inventory, original pixels with the
adjustment hidden, and two independent PNG exports. Its flattened PNG is a
standalone review artifact.

FigCraft's selected Windows 0.18.1 layout recipe builds and reopens an editable
component set with auto layout and a variant-switch interaction. The batch
commands use the owned directory as their permitted read and write root. Static
export runs through the confined-runner port. The standalone review carries
the compact sRGB PNG and declares the interaction retained in its native file.

DeckCraft's selected Windows 0.18.1 recipe retains a custom master layout and
the editable slide transition. The adapter checks 960 by 540 point geometry,
the zero-based destination index and the fade duration. Two fresh midpoint
renders must agree before the still is retained for independent review.

LightCraft's selected Windows 0.21.1 treatment uses a fresh single-owner
library and pins the original JPEG. The adapter retains the native snapshot
with its exposure adjustment and rebuilds it into a fresh library to verify
the color profile and exact rendered pixels. Standalone review exposes the
snapshot and its required original location.

EffectCraft's selected Windows 0.24.1 recipe retains the native composition,
editable label, backing mask and exact installed Arial dependency. Its
standalone sequence covers a half-open window on the verified 24 fps source
clock. The first frame rendered by time and by source frame index must agree
with the partial render before the review export is retained.

Native provider publication extends the existing animation catalog. The package
reader checks its external root, byte fingerprints, declared source roles,
review references, rights and local parameter schema before independent source
inspection. An explicit approval against the current catalog version retains
the verified bytes in a provider-scoped external store and publishes hash-only
source provenance. An identical retry verifies the retained package and returns
the existing promotion without adding an event.

Native kit instantiation verifies the exact catalog version and rechecks the
provider store's retained source, reviews and rights. The selected video's
component instance records its parameters and project-owned source copies.
An explicit upgrade creates a new version-pinned instance linked to the
previous record. Its contextual review follows the existing video gates.

Native kit sharing requires explicit selection of the origin provider and exact
recipient names in the published source rights. The project copy records both
identities. Reconstruction verifies the copied rights, their package hashes
and the current project provider before accepting the shared source closure.

The AniCraft lower-third profile authors 16:9 and 9:16 on their declared
canvases. Both use the same phase clock and width-scaled typography. The
portrait layout anchors the plate near three quarters of the canvas height
and checks every visible alpha frame against its independently measured bounds.

The optional AniCraft secondary label is a second native text element in
the same animated symbol. Source inspection checks its outline, font and
measured width. An approved revision can change either recorded label while
preserving the source and the selected design's text slots.

The opt-in AniCraft fixed hold uses the same readable plate position with
clear frames at the start and end. Source inspection binds its exact keyframe
spans, and export verification requires identical frames through the visible
hold. Saved-source text revisions preserve the reviewed motion profile.

A saved-source text revision starts from an immutable job-owned copy and saves
into a separate revision folder. The native adapter observes the selected edit
command signatures and compares the new document with the preserved design.
The receipt retains the original source, revision recipe and decoded output.

Copy-only reuse binds a selected native export to a new project's exact
provider, editable source bytes, parameters, render contract and installed
tool fingerprints. It copies the verified component frames, native revision
and recipe into the new job without an application session. The new proof
receives its own canonical placement and source binding. Native label
instances resolve omitted settings from the reviewed template and retain its
qualified font.

## Motion engine selection and code-drawn capture (feature 012)

HyperFrames remains the default. The pure shared motion policy resolves invocation, pinned run, project/video, provider/channel and global preferences, in that order. Strict saved IDs are hyperframes, remotion, and code-drawn; Remotion retains its existing unsupported execution adapter. A new default never rewrites a recorded animation revision or creator decision. Explicit new engine/source authoring uses existing revision invalidation. Installed motion and pipeline routers resolve current no-framework intent before loading engine-specific skills.

The advanced code-drawn route is model-neutral Canvas, SVG, or optional pinned standalone p5.brush. The shared motion module owns preferences, source contracts and canonical coordination; motion_runtime owns read-only optional-runtime discovery. The motion adapter owns Playwright/Chromium capture, local allowlisting, independent arbitrary-frame checks, PNG capture and FFmpeg lossless silent FFV1/BGRA publication. Playwright's pinned driver, internal Node and templates ship in the onedir engine; managed browser binaries, FFmpeg and optional local brush provisioning remain explicit runtime installation. There is one packaged template owner.

Canonical authority flows manifest/source snapshot → logical Animation + Tracks source reference → original input lock → generated receipt → frozen ProofPlan. CMap/Sync approvals and current BMap/Tracks/Animation dependencies are derived from real workspace stores. BMap/Tracks own timing and placement; source strategy has no clock and cannot point forward to output hashes. The injected outer composition observes the actual browser/driver/graphics/encoder environment. Timeline services consume observations or a trusted verifier callback and import no renderer. Direct and recursive admission reject stale bytes, bindings, implementations and prohibited output ancestry even when a file is renamed as a font or dependency. Standalone capture conveys no canonical admission or creator approval.

The existing FFmpeg ProofPlan path handles generated-clip and overlay-video. It freezes receipt, lock, frame range, placement and stable z-order; partial proofs retain the original local-frame phase across cuts. Original source audio keeps its canonical graph and envelope. Unsupported mixing/event envelopes fail before output. Explicit FFV1/PCM Matroska conformance uses this same graph for exact decoded pixel and sample checks; normal delivery encoding stays separately checked. Reconstruction retains the complete declared source/dependency/receipt/lock closure and can remove only regenerable output under existing cleanup authority.

Canonical HyperFrames instances use source-only component registrations referenced
by logical Tracks generators and Animation components. The binding service derives
the exact BMap cue, canonical canvas placement, original-media closure and all five
current map heads without pointing Tracks forward to generated output hashes.
The outer composition owns browser/encoder observations and lossless PNG-sequence
materialization; timeline admission consumes fresh observations and imports no
renderer. Frozen vendor scripts are admitted only with explicit local-library
fingerprints; authored HTML/JavaScript retains deterministic-source checks.
Generated receipts require unchanged source/tool identities, exact silent
FFV1/BGRA output and matching seek/encoded-frame evidence. Proof compilation
also verifies source range, ordering and exact canonical-to-preview geometry.

Qualified HyperFrames browser observations are reused only inside one native
proof validation batch, keyed by the complete binding, receipt, output and
canonical lock. Every use still passes native admission. Original inputs,
tools, output and receipt bytes are enrolled in the enclosing fresh closing
guard, including dependencies observed by nested binding checks. Another batch
captures again; no observation cache persists across proofs.

Binding resolution and placed rendering share the enclosing fingerprint stage
only inside that native batch. Every use still resolves current canonical
authority, source membership and receipt admission; byte observations remain
scoped to the batch and all enrolled dependencies receive a fresh closing hash.
Standalone binding resolution and rendering retain their independent stages.
Private per-window PCM uses a separate fingerprint scope; its cleanup must not
leave a deleted temporary output in the enclosing dependency guard.
Historical preview inventory also owns a separate fingerprint scope: these
quarantine examples are negative evidence, not contributing inputs. Renaming a
temporary export cannot enroll its old path in the closing source guard;
copied preview ancestry and actual input mutations remain rejected.

Canonical proof media resolution maps locked audio trim IDs to current Tracks
audio-source fingerprints using both the exact digest and resolved locator.
Several cues can share one original asset. Conflicting IDs or origin metadata
are rejected; unowned, relabelled or unresolved media cannot gain admission.
Resolution remains metadata-only, with byte and recursive ancestry checks in
the normal preflight and executor.

Canonical HyperFrames PNG production and independent seek observations use the
same native snapshot raster backend, in separate browser contexts. Production
captures every frame in bounded batches of at most 128 before silent lossless
encoding. Independent forward/reverse captures and every encoded RGBA frame
remain exact comparisons. The sealed tool environment names this raster backend;
different browser capture paths are not assumed to have identical rounding.
Original source, lifecycle and deterministic-authoring validation plus strict
native checks remain prerequisites.

Both paths use a private copy of the frozen source closure to initialize the seek
runtime with the declared rational render frame rate.
This compatibility bridge is needed when the installed snapshot command defaults
to a different frame rate and exposes no frame-rate option. It changes neither
registered source bytes nor vendor files. Temporary copies have an independently closed
byte-verification guard before clock injection and cleanup; the enclosing proof
guard retains responsibility for original sources and tools. The observed environment seals the bridge policy,
and independent forward/reverse snapshots must match the corresponding encoded
frames exactly. Missing or mismatched evidence rejects admission.

Only a multi-window native microproof gate opts into ephemeral full-placement
video stages. Their provenance binds the full plan, canonical heads, placement,
source, render contract, implementation and tool bytes. Exact integer-frame
slices preserve original sampling and fade phase; ordinary short proofs, stills,
titles and full renders retain their existing paths. Insufficient disk space
falls back to bounded direct rendering. Batch-owned stages survive the fresh
closing guard and are removed only after checking their original resolved root
and rejecting escaped, linked or unexpected contents. No stage is reused across
batches or admitted as an original or prior-proof substitute.

Validation is recorded in specs/012-code-drawn-motion/validation.md: schema/legacy compatibility, seven installed agent profiles, source and extracted native capture, current-environment admission, physical alpha/phase/audio checks, and source-only rematerialization. Local execution identifies Windows AMD64 and its actual graphics renderer; configured Linux/macOS lanes are not claimed as executed locally. See [code-drawn motion](docs/code-drawn-motion.md).

The provider settings validator retains its existing beside-launcher compatibility lookup. Both binary build scripts copy only `providers/avo.provider.schema.json` there before archiving; no provider identities, footage paths or global preferences are packaged. An explicit external `AVO_ROOT` remains responsible for its standard public-schema tree. Scoped writes are validated before replacement and retain unrelated settings.

Compatibility also preserves generic projects whose inferred provider has no manifest: absent provider preferences inherit global/default settings. Explicit provider targets and existing malformed manifests still fail validation; inspection does not create provider files. This keeps optional creative briefing and raw project intake usable without broadening preference writes.

Native proof review shares the existing cut-lineage dispatcher and source-fidelity adapter. Later checkpoints use the generic persisted ProofPlan verifier, while cut-proof retains its strict checkpoint verifier. Native final fidelity derives an explicit `nativeBasis` from current plan/source/generated provenance, microproof gate and actual FFprobe observations; it never fabricates legacy delivery-policy/picture-lineage envelopes. Its verified scope is progressive 8-bit SDR with the executor's supported frozen graph, exact geometry/rational rate/frame count/codecs/pixel format and stereo audio/duration. Untagged 8-bit source is interpreted as SDR; HDR/wide-gamut/high-bit-depth/interlaced or unsupported graphs remain blocked. Existing assembly evaluation and human, transcript, rights/accessibility and Watch authority are unchanged.

Regression revalidation uses the native dependency dispatcher to verify native
ProofPlan source aliases and their aggregate raw hash. Legacy assembly
`rawFingerprints` retain their separate compatibility path. Neither format skips
current-input, source-byte, graph or microproof validation. Coverage includes
native cut regression approval and rejection of altered source bytes and locks.

Checkpoint QC retains every required visual/cue window while optionally exposing
separate `requiredTranscriptionWindows` from its original cut-risk and join
requirements. ReviewRunner uses that explicit list, including an empty list,
only for ASR word-risk analysis and its evidence scope. Watch still receives all
required windows and QC evidence/statuses remain intact. Older QC producers that
omit the field keep their existing routing. A silent graphic no longer implies
that spoken words must occur there; real speech-risk obligations remain required.

Cutting's existing runtime references now allow explicit CPU/CUDA execution for
transcription and isolated WhisperX alignment. CPU remains the compatibility
default. Device/precision bind the transcription cache; alignment records its
requested device and fails when CUDA is unavailable. No runtime provisions
packages or manages the vision server. The caller serializes GPU speech and
vision stages, and the media adapter retains its per-instance speech lock.
Offline model manifests, source clocks and character evidence retain their
existing boundaries. Retake discovery separates backward timestamp jumps rather
than creating inverted/overlapping attempts. Unit coverage checks device
propagation, cache invalidation, CPU compatibility and nonmonotonic intervals.
See [sequential GPU execution](docs/cutting-gpu-execution.md).

Native cutting signal verification derives its optional AAC reference encoding
from the frozen ProofPlan output and identical-channel routing. It reconstructs
the complete window from fingerprinted originals with the declared node envelopes,
then applies the executor's shared 192 kbps AAC contract before analysis decoding.
This accounts for lossy codec changes in short consonant windows without weakening
word, fade, sample-coverage, correlation or residual checks. Unknown contracts
fail closed; lossless conformance and legacy PCM references keep their existing
path. Candidate audio never supplies the expected signal. Verification claims
record the reference encoding, and implementation bindings invalidate old proofs.
Synthetic encoded tests preserve detection of missing quiet onsets and tails.

Native ProofPlan mixing keeps the existing sequential source-cut dialogue path
and adds explicitly declared music, SFX and ambience nodes in the absolute
48 kHz sample domain. The media adapter validates every original through the
same fingerprint, ancestry and channel-routing boundary before rendering. Audio
resampling requirements cover source, music, SFX and ambience leaves equally;
missing, unused or mismatched conversion operations remain errors. Audio
events must identify their exact declared node and onset; unsupported effects,
missing events and clock mismatches fail closed. The mix adapter accepts only
finite ranges, literal gain, bounded fades and declared sidechain ducking. A
lossless same-plan dialogue intermediate supplies the lead without reading an
earlier proof. Float PCM preserves headroom until the single final audio encode.
Independent finite picture/audio inputs reach EOF so a video frame-count stop
cannot discard the last PCM packet of a microproof.

Post-cut source gain controls live in optional Tracks
`audioTracks.sourceMixAdjustments`, not a replacement CMap or duplicate audio
layer. Each control binds an enabled imported placement, original fingerprint,
stream and channel selection. The ProofPlan compiler applies its gain/ceiling
deltas once to the existing source node; preflight checks the exact result.
Cut proofs retain the original CMap mix. Legacy assembly rendering rejects these
controls rather than silently ignoring them. Existing Tracks without controls
are unchanged; schema, source-binding and compile/preflight tests cover this path.

Tracks regions may declare their rational timebase. Omitted timebases retain
legacy milliseconds. Cue containment compares exact rational seconds rather
than integers from potentially different clocks; the compatibility video/audio
compilers already consume the region timebase. Coverage includes frame-domain
projection, cross-clock truncation rejection, source validation, actual mixed
audio placement and absolute-clock microproof equivalence. See
[native proof audio mixing](docs/native-proof-audio-mixing.md).

Proof execution opts into a context-local fingerprint stage so repeated references
to the same immutable multi-gigabyte source share one byte observation. The
default fingerprint API remains uncached. File identity/stat changes invalidate
an observation; returned dictionaries cannot mutate the cache. Before publishing
an encoded candidate, a fresh nested stage rehashes sources and generated closure
inputs rather than reusing render-start observations. This detects changes even
when size and modification time were preserved. Exceptions restore the previous
context. Tests cover cache scope, unmodified default behavior, changed bytes and
the final proof-publication guard. No source/proof ancestry admission is removed.

An admitted generated asset may carry several visual events. Smaller event
windows require exactly one matching `parameters.eventBindings` declaration in
the checked generated receipt, including role and asset-local frame range. The
executor projects that range through the frozen source/output placement and
rejects missing, shifted, ambiguous or mismatched bindings. This supports a
shared seek-safe alpha carrier without falsely declaring its complete duration
as every title's visible range. Existing exact-operation event behavior remains
compatible; generated admission and pixel/runtime checks remain independent.

SFX events may retain a source attack before the impact frame. Their explicit
native-rate transient offset is converted with the shared sample-boundary rule;
the node starts at impact minus that offset. Rate, source bounds and any declared
resolved offset must agree. This avoids silently scheduling effects with leading
quiet material late or trimming their attack to force synchronization.

Native microproof execution has an explicit immutable validation batch in
`avo.timeline.proof_validation_stage`. It shares byte observations and decoded
pixel observations across required windows, then freshly hashes every observed
dependency before publishing the batch gate. A changed dependency, including
changed bytes with preserved file metadata, prevents publication. Standalone
proof execution retains its separate fresh final validation stage. The timeline
context exposes no media implementation dependency; media adapters opt into it.

Repeated generic generated-asset admissions can share a checked record within
one validation stage. The key includes the source, generated record and input
lock, with current canonical locks and record bytes checked on reuse. Placement
and range checks still run for each operation; code-drawn runtime admission is
never cached this way. Generated video inspection decodes the complete frame
stream once to obtain both frame count and alpha observations. Large-file
inspection budgets scale with byte size, while required frame coverage and
opacity checks remain unchanged.

Automatically selected representative operation windows are bounded to five
seconds at the declared rational output frame rate. Explicit requested windows,
historical windows and mandatory editorial join coverage retain their full
declared ranges. This limits redundant representative rendering without
truncating a required verification window.

## Footage library administration (BL-010 / feature 013)

The [library organization implementation](docs/library-organize.md) adds a
library boundary alongside video editing, with its own explicitly selected
external root and provider. `library_cli` is the shared clone/installed command
adapter; `LibraryService` coordinates inventory, proposals, evidence, moves,
search and batches. The slash gateway routes `/avo.organize` to the same native
operations. Default scan probes metadata and builds an offline HTML/text folder
review without model calls, source moves or a video manifest. Browser edits are
untrusted requests for native validation, never filesystem or approval authority.
The shared command registry classifies `organize` as `Admin` with no canonical
timeline mutation permission; library approval cannot authorize editing or rendering.

`avo.library.rules` owns record/path validation; `store` owns immutable library
documents, the small atomic `edit/library-index.json` head and a nonblocking
OS-owned writer lock. Library bodies reuse canonical hashing and publication
utilities, not timeline artifact schemas or editorial revision authority.
Inventory snapshots retain stable recording identities, observations and
transcript references. Metadata observations permit cheap unchanged refreshes;
exact selected-source hashes and file identity are prepared for move/transcript
approval and rechecked at execution. Preparation, decisions, operation events,
recovery and handoffs live under the footage root's `edit/library/` tree.

Source mutation depends on the media adapter
`avo.adapters.media.library_moves`, not an agent shell walker. The tested
capability is fixed local Windows NTFS. A source handle denies concurrent writes
and deletes; verified non-reparse ancestor handles prevent directory replacement.
`SetFileInformationByHandle` performs a no-replace rename, followed by byte and
file-identity verification through the same source handle. The tested Win32
implementation rejects a non-null relative `RootDirectory`; its absolute target
is derived from the pinned destination-directory handle while all ancestors
remain held. This is a documented platform-specific exception, not a copying,
overwriting or undocumented-API fallback. Other storage/platforms refuse apply.
Referenced or unverifiably owned media stays at registered paths; immutable
video timelines are not relinked by rewriting historical JSON.

Move orchestration records intent before mutation and verified outcomes before
publishing new inventory. Resume reconciles durable state against actual
source/destination evidence. Reversal is another prepared proposal and explicit
decision. Cancellation has a separate durable control record so it can be
acknowledged while a mutation/worker owns the main lock; the owner stops new
admissions and reports an already running item until settled.

Search builds a disposable SQLite/FTS projection from committed inventory and
admitted transcript evidence. Results, cursors and selection bind a generation;
warm queries freshly validate bounded returned candidates and actual quoted
transcript bytes, while broader coverage remains an explicitly labeled snapshot.
Handoff revalidates original-source paths/ranges and carries restrictions and
shared usage references. Missing speech evidence stays unsearched. Cache loss,
network storage or unavailable FTS has an explicit degraded path, without model
downloads or a claim that performance targets remain met.

Approved batches resolve the existing model/routing catalog and dispatch the
local transcription adapter through `avo.adapters.run_job`. The supervised
worker admits only the exact approved recordings/configuration, uses prepared
CPU/int8 model files, one worker and bounded CPU threads, preserves per-record
outputs and resumes valid completed work. The cumulative time allowance stops
new admissions rather than killing current inference; interrupted downtime is
conservative and cannot reset the approved budget. Paid dispatch remains
unavailable without an enforceable maximum-charge adapter. Library usage belongs
once to the batch attempt; video handoffs reference it without allocating it
once per video. Default single-file/directory transcription remains compatible;
explicit output paths, CPU limits and requested-versus-detected language cache
metadata are additive interfaces.

Independent progress heartbeats contain lightweight observed state and unknowns.
Footprint/disk observations happen at boundaries, and explicit completion writes
an immutable report without changing the authority head. CLI boundary telemetry
uses the existing reporter; heartbeats do not repeatedly write global state.
Metadata-only phases supply an explicit empty model-source disclosure, avoiding
unrelated hardware/model resolution while preserving the reporter's legacy defaults.
Closed video/preservation receipts block library mutations. Cleanup integrates
the exact reviewed persistent paths through existing `cleanup.preservePaths`
and reconstruction protection, including library raw sources; disposable search
cache/review output is not retained as recovery authority. The canonical
instruction explicitly distinguishes durable library metadata from disposable
post-render scratch. Organization never performs automatic post-render cleanup.

Validation covers library contracts/inventory/proposals, real native move and
recovery fault boundaries, bounded search/handoffs, offline review, prepared
local ASR, cancellation/resume, retention and legacy compatibility. Installer
checks copy the routed organize guidance through all seven existing fallback
profiles and the Cursor wrapper. These checks do not certify a network installer
run or every packaged release. Frozen reference measurements pass native search,
actual-ASR contention, visible review/interaction and unchanged-refresh budgets.
The requested five-person comprehension study remains explicitly pending, with
no participant results claimed. Full repository quality signoff is separately
blocked by an existing locked dependency advisory. See the local feature 013
validation records for acceptance evidence.

Native cutting microproofs with music, effects or ambience reconstruct the
declared mix around independently extracted original dialogue before comparing
the encoded candidate. The QC adapter reuses source admission, sample clocks,
routing, gain and ducking from the frozen audio graph; it never extracts its
reference from a candidate. Stereo is preserved through the reference AAC encode.
Dialogue-only checks retain their existing path and thresholds. Integration
checks cover a valid stereo bed, missing consonant onsets/tails and changed
source fingerprints. This physical conformance evidence does not replace
intelligibility review or human listening approval.

Each cutting verification window owns scratch paths bound to its candidate and
review basis, so an immutable validation batch never overwrites a fingerprinted
mix from another window. Native-reference extraction opts into the renderer's
sample-addressed input seek from a same-batch original PCM decode, avoiding
container timestamp rounding while preserving fingerprint, stream, channel,
sample-count and truncation checks. The decode is shared only within the source
verification batch and checked for mutation; rendering still reads the original
media. Original alignment and
analysis extraction retain their existing default sample-clock path. Tests
compare exact routed PCM bounds, reject a missing source tail and verify two
mixed windows under the same closing fingerprint guard.

Within one immutable proof-validation batch, cutting previews validate source
analysis documents once and retain only the word/routing projection needed for
subsequent windows. Every reuse checks the original file fingerprints, and the
batch still closes with fresh byte hashes. The cache ends with that batch;
ordinary analysis reads retain full validation. Mutation, path containment,
scope changes and caller modifications to returned words have regression checks.

Native MP4 proofs and independently encoded QC references use the output audio
sample rate for the movie clock. The
default millisecond movie clock can round an AAC edit-list boundary down and
discard retained samples at a video-frame edge. This changes container timing
precision only; source ranges, fades, PCM mixing and QC coverage checks remain
unchanged. Actual-codec tests verify exact audio duration for short 60 fps proofs
and matching microproofs, including boundaries between milliseconds.


### Resolve handoff provenance and ongoing selection

The OTIO boundary remains a bounded raw inspector plus an injected, pinned native
core reader and media probes. The timeline package owns semantic qualification,
proposal/receipt locks, exact clocks, source mappings and element dispositions.
CLI/native worker code stays in adapters/entrypoints; domain code imports no
OTIO runtime, FFmpeg adapter, CLI or MCP implementation. Imported strings and
reference notes never become instructions or approval.

Actual moving-picture admission verifies the complete presentation timestamp
grid against original bytes, independent of nominal/average rate headers. Native
rendering rechecks the same clock and bounds every selected range by its verified
presented-frame count. Self-contained demuxers and file-only protocols
exclude nested playlists/external media; still input uses a literal single-image
route. Unsupported rates, packet correspondence, layouts or treatments block.
No fallback flattened program is admitted. The proof implementation digest
includes the placed compiler/executor, media policy, timestamp and ancestry
verification dependencies.

Import activation selects exactly one CMap revision under the shared kernel
writer and exact-head comparison. The immutable validation binds the displayed
current-edit diff. Intent records the exact prior revision/snapshot; postcommit
recovery replays descendant invalidation and explicitly reconciles the draft
lifecycle without reusing candidate/review authority. Return writes a new CMap
revision from recorded prior content with current original-byte/Sync checks; its
inputEvidenceRefs carry an optional relative path and file-byte hash for the
typed return journal. The immutable revision contract reuses the shared evidence
reference schema. Historical exact retries do not select over later edits.

The canonical ancestor and exact activation→receipt→proposal→export→result chain
validate import origin; mutable session refs are bookkeeping. Proposal filenames
use semantic hashes while origin proposalSha256 uses file bytes. Legacy
normalizer1 canonical imports may omit root locks but still require the complete
contained identity/ancestor chain; new receipts bind canonical/import roots.
Before releasing recovery, source, context, Sync and retained evidence are
freshly checked. Uncertain recovery markers stay guarded. Actor/reason text follows canonical store normalization, including recovery of
earlier padded journals without rewriting immutable evidence. Index-write failure
cleanup retains an immutable body if selection committed or cannot be inspected.

Reconstruction follows all historical import origins, repair predecessors and
canonical return refs through bounded exact evidence closure. It never blanket
retains imports. Cleanup resolves the declared project (including alternate
manifest/custom timeline paths), verifies the current bundle and holds the same
writer through deletion. Persistent kernel locks are never deletion candidates.
External originals are verified externalSources references; bundle.files remain
local. Legacy source locators retain the top-level/fingerprint fallback and
rawDir-relative interpretation used by existing canonical reconstruction. Retained materialization output fingerprints quarantine renamed or deleted
proof/master media without treating original dependency hashes as outputs.

The optional native reader is included by explicit resolve-import build extras,
with OpenTimelineIO metadata/licenses/native extensions and schema resources. A
private engine worker dispatch preserves plugin-disabled isolated execution in
frozen builds. The local Windows x64 reader smoke passes public inspection and
prepare/validate with intentionally missing originals; other frozen platforms,
real Resolve exports, long-source throughput and creator review remain separate
qualification. Existing ordinary canonical layouts/default audio/engine and
source-only import preservation remain distinct, with compatibility regressions.

## Editing craft parity (feature 017, implementation in progress)

The local working design is `specs/017-editing-craft-parity/plan.md`; numbered
working specs remain ignored by existing repository policy. Scoped preferences,
typed request freezing and the default motion-review projection are implemented.
Untimed proposal/selection and recoverable canonical application use the existing
timeline owners. The sound catalogue and descriptor search are local source-read
and saved-metadata operations respectively; semantic execution has an explicit
isolated optional boundary. Camera, visual analysis, sound placement and source
preparation use explicit selections. Editor interchange exposes source-preserving
validation, returned XML review and selected cuts through the normal trim owner.
Its production targets await version-specific qualification.

Motion map and linked lightweight storyboard are built-in, engine-independent
projections at applicable motion planning/review. They join the selected brief,
untimed proposals and exact available CMap/BMap/Tracks/Animation/Sync heads,
including absence/static/unresolved state. Status remains metadata-only and
cannot initialize canonical records, run models or render. Explicit authoring
and review publish immutable derived views; no second timeline is introduced.

`MotionAuthoringService` freezes selected direction/options in existing run
extensions, stores immutable concept/decision documents and projects them into
the same default map. It prevalidates full prospective BMap/Tracks/Animation
revisions under the timeline writer, then publishes through each owner with exact
prepared identities. A narrowly scoped pending-application guard blocks unrelated
canonical work until the same operation recovers. Receipts record staged,
committing, committed or recovery-needed state; they do not transfer approval.

Motion retention preserves legacy metadata that claims no head or revisions as
opaque fingerprinted bytes. Claimed heads/revisions and their motion evidence
remain strictly validated. This compatibility boundary grants no canonical read,
render or approval authority to a legacy metadata stub.

`SfxCatalogService` retains immutable project-local generations and separates
source-bound measurement facts from manual curation, rights and reviewed markers.
It reuses shared safe-path/library guards without invoking media organization.
Warm descriptor searches perform no source enumeration, decode or model work.
An explicit semantic operation injects a ranker and paired local CLAP worker;
manifest/model/preprocessing/runtime identities must agree before cosine scores
are accepted. The optional worker uses offline local files and bounded validated
vectors; ordinary model defaults and proof capability registration stay unchanged.
No model package or weights are an AVO core prerequisite. The distributions
include separate Windows CPU wheel locks for CLAP and face analysis. Explicit
local runtime qualification uses `AVO_TEST_CLAP_PIN` without changing ordinary
job defaults;
the real worker test records joint-space/manifest identity, normalized vectors,
exact source-bound cache reuse and changed-source rejection. Human suitability
and listening acceptance remain separate.

Advanced camera strategy validation reserves a closed relative-behavior extension
and publishes the revision reference with an index-v2 capability fence in one
atomic replacement. Generic snapshot writers and metadata-only readers enforce
the same guard; existing v1 snapshots do not cause an upgrade on inspection.
The pure camera planner derives frames from BMap and binds moves to exact source
occurrences, geometry, source bytes and frozen options. Camera proof compilation
uses a strict v2 operation contract and requires a qualified native implementation;
legacy proof contracts are unchanged. The selected native route verifies tool
and input identity before executing and leaves creative approval to review.

Selected untimed camera recipes expand inside `MotionAuthoringService` into
strict relative paths with frozen options, source identity and display geometry.
The pure recipe factory performs no source access or canonical writes. Stable
concept IDs retain unchanged paths across revisions; publication rejects a path,
option or component that differs from the selected concept. BMap and the existing
camera compiler remain the only timing and source-occurrence authorities.

The native camera sampler accepts sealed numeric paths over freshly verified
original-source occurrences. Its frame expressions retain the complete cue
interval during partial renders and run before independent captions or graphics.
Contiguous and placed execution share this source-bound sampler. Explicit
precision composition uses 16-bit RGB/alpha planes and bounded raw picture
chunks; opaque alpha insertion/removal copies planes instead of introducing a
libswscale RGB/RGBA matrix round trip. Legacy proofs retain their existing pixel
path. Optional placed-stage reuse is disabled for the new precision profile
until its complete camera recipe is qualified for caching.
An accepted delivery profile keeps RGB16 through source sampling and independent
composition, then performs one final BT.709 conversion with square output pixels.
Unsupported timing, source geometry and fidelity combinations fail preflight. Runtime evidence and
remaining activation requirements are documented in
[`docs/source-picture-camera-rendering.md`](docs/source-picture-camera-rendering.md).

Selected native camera execution records actual tool bytes/version identities,
implementation code and the complete recipe in the existing producer record.
The adapter binds its observed environment to preflight and verifies execution
against it; the environment changes the microproof gate's preflight hash. Existing
materialization and reconstruction owners retain these records without another
source ledger. Packaged native implementations bind program bytes containing the
embedded code, while checkout fingerprints include camera and precision modules.
No runtime probe is added to ordinary metadata-only motion views.

Explicit camera proposal/application bind the observed installed environment to
selected recipes, exact dispositions and existing recoverable canonical owners.
Application is confined to the selected picture components/layers, rejects
duplicate scope identities and preserves unrelated graphics/dialogue/global
settings. Generic plan application cannot bypass the selected camera runtime.
Runtime inspection follows known Chocolatey launcher targets and fingerprints the
final executable as well as launcher bytes; tools stay separately installed.
Motion-review generator 1.2.0 derives planned/authored before/during/after states
from the relative path and unambiguous component links, while retaining readable
1.1.0 reports. Gate JSON joins existing reconstruction ancestry evidence; disposable
proof clips and tool binaries are not reconstruction sources. Actual native
fixtures verify full/window source sampling, independent overlays, color/depth,
runtime identity and unsupported-profile rejection. These checks do not replace
Watch, listening or creator suitability review.

Sound candidate fitting is a pure timeline primitive over validated catalogue
metadata and an explicit native-sample trim. Shared catalogue identities and
validation live in `avo.sfx_contracts`; the existing catalogue imports those same
unchanged checks, keeping source execution outside the planner. It reuses the existing event clock,
keeps useful attacks/tails, and returns unresolved pre-roll/tail/rights/visibility
cases instead of changing picture or audio ranges. Its derived hash binds clock,
source/measurement and current annotation identities. It creates no source reads,
canonical timing, selection, gain policy or listening approval. Publication and
encoded contextual qualification belong to their existing owners.

Optional catalogue descriptions and categories extend the existing strict
curation contract. Generic annotation revision/expected-generation controls
remain authoritative; descriptor ranking includes those labels and shared
eligibility enforces exact category filters for descriptor and semantic modes.
Missing fields preserve legacy entries without migration. No new index, runtime,
source analysis or rights claim follows from these labels.

`avo.sfx_preferences` explicitly promotes selected portable descriptors and a
library/source-byte identity into bounded `routingOverrides.sfxFavorites` in the
existing provider manifest. Existing preference schema/byte guards and writer
locks preserve unrelated settings and recheck the current catalogue before
publication. Native/MCP mutations bind exact request bytes and provider scope;
they gain no canonical timeline authority. Selected scans alone seed new matching
entries, freeze their preference snapshot through resume and expose origin hashes
in catalogue/search metadata. Existing project choices and all source, rights,
marker, measurement and approval owners remain independent. No second project
state store, media copying or default provider lookup is added.

Explicit sound proposals now reuse `MotionAuthoringService` head guards and
`PipelineRunStore` option freezing, with strict bounded intent/proposal contracts
and immutable metadata below `edit/motion/sound/`. The timeline service derives
events only from current motion items and canonical cue timing, captures selected
sound direction, and calls an injected catalogue for generation-bound candidates.
Silence and unresolved anchors remain first-class outcomes. Native/MCP entry
points share the same request and operation replay; they do not scan source media,
provision models, publish audio or approve listening. Proposal validation precedes
option freezing. Unregistered drafts do not enter reconstruction closure; canonical
publication and typed evidence retention use their dedicated owners below.
Pure per-event choice preparation reuses the existing overlay role and channel
validators. It freezes entry/marker/mix identities and uses the same native event
clock for before/after reports, while exposing repeated sources and coincident
attacks. Explicit source peak/fade limits cannot establish combined-mix safety or
listening acceptance; current source/catalogue/head checks stay with publication.
The pure sound graph compiler translates frozen choices to existing native
trim/gain/fade/duck nodes and timed events. It retains absolute program coordinates
through cut windows and makes identical compilation idempotent. Existing source
processing remains unchanged; extending a program mix requires its exact original
node set and policy. Native execution still admits original source bytes and
performs rendering. This qualification kernel is not a canonical sound publisher.
Source-native fitting lives in the data-only `timeline.sound_fitting` module so
canonical readers can reuse the same validation without importing authoring or
persistence. `sound_planning` retains its existing fitting/error imports for
compatibility; the moved fitting bodies and their failure semantics are unchanged.
JSON budgets, track channel/overlay rules and frozen sound choice validation live
in the data-only `motion_metadata`, `track_rules` and `sound_choices` modules.
Existing review, Tracks and sound-planning imports remain available. Canonical
readers reuse these rules without importing authoring, rendering or models.

Optional camera-node sound anchors use the data-only `timeline.sound_anchors`
resolver. It reads the actual current Animation component through its calling
service, verifies the linked cue/target layer and exact camera path/source, then
derives a phase on BMap's full canonical interval. Proposed camera descriptions
grant no execution authority. Frozen sound opportunities retain the selected
node; native proof admission recomputes it against canonical Animation. Checkout
producer identity includes the sound anchor, admission, fitting and compilation
sources; packaged engines continue to bind their executable bytes. This adds no
timing owner, decoder, model or approval path.

Sound choice advisories compare exact native-sample schedules as rational time,
including retained siblings during per-ID publication. A bounded sweep reports
overlapping event/role pairs and their half-open intervals with explicit report
truncation. Equal-time impact comparisons also respect each output sample rate.
These data-only observations leave source signal, gain/fades/ducking and frozen
choice identities unchanged; they establish no masking measurement or approval.

Selected sound Tracks carry a strict source/choice/cue/request binding and require
the `sound-selection-v1` reader capability. Generic publication atomically updates
the Tracks index to version 2 with its revision reference; unchanged legacy reads
retain version 1. Animation version 2 keeps its separate camera capabilities.
Invalid or resealed choices, changed source/channel/gain/clock bindings, duplicate
contributions and untyped references fail closed. The legacy audio projection
rejects these tracks rather than ignoring their native trim. New readers support
both legacy and selected-sound data; published advanced history retains its reader
fence on later revisions. The internal `timeline.sound_application` service now
publishes explicit per-event selections through the existing BMap/Tracks owners
under the shared timeline writer. Frozen choices bind actual local source bytes
and an injected first-audio-stream probe. Exact owned cue/layer bindings and
current visual contexts prevent replacement from altering unrelated content or
borrowing ordered-layer approval. Silence removes only its selected contribution.
Immutable requests, staged prepared revisions and linked receipts support exact
retry after partial publication, including an interrupted initial operation log.
Recovery rechecks heads, source/catalogue, direction and frozen options; pending
markers remain blocking until the actual publication is reconciled. Completed
replay reports historical heads separately from their currentness.

`timeline.sound_retention` extends the existing bounded motion evidence ledger
with selected sound proposals, their actual operations, receipt history, exact
catalogue generations and pending recovery inputs. Unfinished publication keeps
its actual current catalogue selector, including a stale basis; committed replay
retains frozen metadata without adopting later curation. Catalogue reads share
the data-only catalogue byte limit inside the unchanged total evidence budget.
Canonical/history and explicitly requested work references drive retention; unrelated
drafts and generated review caches do not. The timeline domain owns validation
and publication; `adapters.registry` composes the optional explicit source probe
using the existing ffprobe adapter. Metadata readers never execute it. Native and
MCP apply share the strict saved request, canonical owner permissions and exact
confirmation-byte binding. Recoverable errors report actual heads/receipt/state.
See
[`docs/sound-application.md`](docs/sound-application.md) for the boundary and checks.

Typed sound application selectors preserve exact staged inputs even when staging
is interrupted before its operation log or pending marker. Bounded discovery uses
only the owned selector directory. Generic authoring retention excludes the typed
sound draft collections, then adds their verified dependencies; adjacent creator
notes remain authoring inputs. `timeline.sound_sources` registers current and
still-staged external sound originals with reconstruction's existing
`externalSources` contract and the native sound source identity. Existing
fingerprinting verifies the selected files without copying or decoding a library.
Project-local selected or staged sound assets join the fingerprinted bundle files,
including staging before the first canonical owner write.
The metadata/file coverage path grants no rendering or listening authority.

`timeline.sound_proof` joins current selected Tracks, exact committed publication
recipes and current visual anchors into ordinary proof compilation. It reuses the
pure native graph compiler and adds no decoder, model or media-adapter dependency.
Preflight recomputes the contribution and rejects omissions, altered events/mix,
unpublished recipes and overlapping copies of a selected source. Cut proofs keep
their source-only pass. Optional ducking binds current unmuted dialogue to actual
source/stream/channel routing, including a selected microphone duplicated to
stereo. Native source descriptors declare original ancestry explicitly for the
existing strict media resolver. Physical admission and listening remain separate.
Sound finalization/recovery accepts expected descendant staleness only after an
actual published parent, while preserving unchanged revision and approval checks.
It leaves Animation stale until its existing owner refreshes that dependency.

`timeline.motion_sound_review` derives proposed and selected sound links for the
built-in motion map and storyboard from bounded metadata. Generator 1.3 retains
readable 1.1/1.2 reports. Selected sound adds no visual timing authority; stale
opportunities become unresolved, and foreign or invalid context becomes a gap.
Sound propose/apply reuse the existing report publisher without source/model
execution. Presentation failure preserves valid canonical publication and is
reported separately. Ordinary inspection remains read-only.

Motion-review generator 1.4 projects applied plans against verified publication
heads while preserving immutable proposal bodies and their original basis.
The shared data-only basis comparator keeps authoring and review consistent;
current dependency state and changed direction remain stale. Older 1.1/1.2/1.3
reports remain readable. This presentation correction transfers no proof approval.

Sound programme admission reuses native sequential frame rounding and preserves
placed picture clocks. Existing BMap duration validation still bounds audio cues.
Explicit silence can retire a previously owned contribution after its visual
anchor disappears. Missing audio cues are permitted only for that removal;
present bindings remain exact. Immutable parent Tracks supply historical recipe
verification for replay, while remaining ordered sound contexts stay unchanged.

`timeline.craft_work` links explicit proposal operations to at most 500 typed
references in the existing `PipelineRunStore`, with original request/item/event
scope and no new timing or approval authority. The built-in 1.5 review derives
pending, partial, completed, recovery and unavailable states from exact existing
decisions and receipts. Missing evidence keeps the recorded scope visible; changed
heads, direction, catalogue or active request remain stale. Canonical head guards
read canonical metadata directly instead of traversing these derived views.
Requested pending proposals join the existing bounded reconstruction closure;
unregistered drafts and generated reports remain disposable. Readers neither
decode/hash source media nor execute optional models. Earlier 1.1 through 1.4
reports remain readable. See [`docs/craft-pending-work.md`](docs/craft-pending-work.md).

`timeline.craft_work` records reversible per-ID queue dispositions in the same
run, with bounded append-only request hashes and per-work predecessor checks.
Pure `timeline.craft_work_decisions` rules let lifecycle validation reject
rewritten, detached or conflicting history without importing media execution.
The 1.6 projection separates deferred/closed IDs from actual canonical completion;
it transfers no concept, media or film approval. Native/MCP `pipeline work-decide`
validate a bounded request before project/execution setup and reuse the existing
report publisher. The ordinary pipeline flow remains behind its existing handler.
Unknown scope, stale decision heads, unavailable evidence and partial publication
block decisions. Applied contributions require their canonical revision owners.

`timeline.motion_scope` provides pure exact visual comparisons after audio-only
revisions. Motion review verifies retained canonical metadata with the existing
contained, bounded, schema/hash/reader checks; recorded source/sync identities,
selected direction and the exact Animation revision remain required. Applied
timed visual items can retain direction while the full proposal, composite and
Animation remain stale. No media caching or evidence/approval transfer is added.
Changed visual assembly currently blocks this reuse for the whole assembly.
See [`docs/motion-review-scope.md`](docs/motion-review-scope.md).

`timeline.craft_scope` classifies one canonical-start owner and untrimmed
intersecting context against a bounded complete partition. The native clock
check is shared with sound planning; exact native rounding and placed rates are
preserved. Optional scope views use the existing native/engine/MCP plan routes
and generator 1.8, with no execution setup or approval authority.
`timeline.motion_scope_application` freezes scope in existing immutable requests
and receipts, protects unselected/shared IDs, requires previous owners for
cross-chunk retiming, and records exact applied IDs. The existing run keeps a
bounded typed application history, while existing retention verifies its closure.
Legacy unscoped receipts retain their original meaning. Unique explicit cue
references can associate legacy cues without altering canonical identity;
conflicting claims remain unresolved. See
[`docs/scoped-craft-production.md`](docs/scoped-craft-production.md).

`timeline.sound_scope` applies the same bounded partition to explicit sound
choices. Ownership uses exact scheduled sample time, with both original and
replacement owners required across chunks. Existing immutable sound receipts
freeze current/previous whole intervals and recompute ownership on replay and
retention. Parent BMap validity and exact cut binding remain prerequisites;
unscoped compatibility, source admission, full/window absolute evaluation and
listening/approval boundaries are preserved. No sound state store is added.

Canonical contract validation retains at most four parsed schema registries,
keyed by the complete freshly read schema bytes. Every validation rereads the
current schema files and validates its input document. Changed, missing or
malformed references therefore invalidate parsed reuse without trusting file
timestamps, caching validation results or refreshing media/review approvals.

Motion-review generator 1.9 binds bounded requested-work and context identities
separately from canonical picture/audio heads. Native reports record their
explicit proposal origin and reconstruct current inputs through the same
read-only pipeline context reader, reopening project preferences while retaining
active frozen choices. Relevant sound context binds validated catalogue
metadata. Missing or changed inputs retain historical report files without
source analysis, canonical mutation or approval transfer. Older generators stay
readable as historical views. Scope/report regeneration preserves an identical
canonical ProofPlan; changed full proof dependencies still require normal
reconstruction and owner review.

Preparation coverage uses the pure `timeline.preparation` inspector over existing
source/routing/Sync-bound acoustic and aligned-word facts. Cutting persists its
strict document inside existing immutable source-analysis records and returns
compact review references. The inspector neither decodes nor executes models;
missing facts remain unavailable rather than an empty measured result. Outward
source-tick uncertainty feeds the existing retake protection policy without a
second timing owner or an automatic transcript/cut decision. Explicit editorial
and pause-verification flows retain their current boundaries. Cutting producer
identity includes the inspector and preparation schema.

`timeline.preparation_recovery` freezes explicit source intervals and existing
editing-craft recovery limits in typed cutting documents. The existing cutting
journal serializes durable requests and source-stable attempt claims before
inference. OS-owned per-interval locks prevent duplicate concurrent execution;
immutable deterministic results survive interruption before journal publication.
Exact replay reuses evidence while changed source/routing/Sync/original analysis,
model or producer identities retain stale results without automatic retry.
`CuttingAnalysisAdapter.recover` reuses routed native extraction, the existing
local transcriber and optional isolated alignment. Actual source offsets and
reduced context remain explicit; unavailable alignment preserves text without
word-exact authority. No transcript replacement or CMap approval is granted.

`preparation_cli` and the model-tool bridge expose metadata-only coverage and an
explicit selected recovery operation. Coverage constructs no model adapter and
does not verify source bytes. Recovery confirmation binds exact bounded request
bytes. `timeline.preparation_retention` verifies a bounded transitive journal
closure for reconstruction and fallback inventory, including unpublished durable
results, without retaining extracted PCM or unreferenced drafts.

`timeline.preparation_choices` records explicit original/recovered/reject/defer
decisions in the same cutting journal, guarded by current-head CAS, complete
overlapping predecessor identities and exact result/request scope. Immutable
alternatives and superseded decisions remain reconstruction dependencies.
`timeline.preparation_selected` derives a bounded source-unit view for existing
cutting analysis. Pending/deferred, stale and unqualified timing ranges retain
speech protection. Replaced word/character spans cannot silently cross selected
boundaries, and recovered text drops affected pause certifications. Selection
grants no cut approval, replaces no source transcript and starts no inference.
Recovered choices revalidate source/model/execution bindings; choosing original,
rejecting or deferring requires no model adapter. Cutting producer dependencies
include the selected-evidence documents and implementation. Metadata-only
coverage retains its existing no-source/no-model boundary. Disjoint measured
windows preserve their unmeasured gaps rather than claiming envelope coverage.

`timeline.preparation_facts` composes selected measured windows through the same
pure coverage rules. Each incoming measurement needs its own observed facts and
tool provenance; it cannot borrow missing original provenance. Valid original
measurements and activity remain available, while unmeasured source time remains
protected. A previously blocked analysis gains only the selected actual coverage,
and unmeasured or affected pause certifications are not transferred. Cutting
producer bindings include this composer. No media/model execution or new timing
owner is introduced. Actual local alignment validation additionally verifies
cutting consumes the selected facts without another analysis call.

Explicit source-point consumers can select a contiguous CMap `segment_id` through
the existing raw-to-output mapper. This identifies repeated occurrences without
changing program offsets or the default mapping. The selected segment owns its
native source clock; an unknown occurrence stays unresolved. Placed CMaps retain
their placement/track selectors and reject the contiguous-only selector. This is
a mapping primitive, not a second timeline or automatic spoken-sound trigger.

Optional original-source sound anchors resolve through the existing CMap mapping
primitive in `timeline.sound_anchors`. They bind the raw fingerprint, rational
source point and exact segment/placement, reject ambiguous or unsupported inverse
mapping, and require the derived output frame inside the linked cue. Proposals
read current metadata only when this option is selected; canonical publication
binds the unchanged heads and verifies originals. Native sound admission reuses
the same resolver against current CMap and compares the frozen opportunity.
Mapping implementation bytes join native producer identity, so cached proof
evidence cannot survive an unqualified mapping change. Encoded full/window tests
measure the selected transient while preserving source picture and the original
CMap. This route does not infer spoken timing or grant listening approval.

Current local speech dependency inspection lives in the shared
`avo.speech_dependencies` metadata helper. The cutting adapter retains its
existing interfaces, runtime selection and failure behavior while delegating
dependency-byte/version checks. The helper imports no media adapter and loads
no model; cutting and recovery producer identities bind its implementation.
Before/after adapter and recovery tests preserve the existing behavior, including
configured ASR with separate alignment and changed local dependency bytes.

Optional word-timed sound remains a source anchor on the existing CMap clock.
`timeline.preparation_words` qualifies an immutable word's measured, aligned and
unprotected source time against current model facts. `timeline.sound_word_evidence`
reuses CuttingStore/preparation selection and bounded retention; it binds exact
original or selected-result provenance without a new mutable store. Shared speech
dependency metadata reads package versions from the declared isolated environment
without importing its runtimes. Actual initial analysis records dependencies
before/after the pass and rejects changes. Proposals freeze concrete source time,
word and selection hashes; publication, native sound admission and existing-plan
approval recheck them. Exact analysis roots survive reconstruction without a
recovery journal. Model packages and temporary PCM remain outside this metadata
closure. Ordinary intents do no speech work. Unit, publication, actual encoded
full/window and separately prepared Portuguese ASR/alignment tests cover these
boundaries; listening and creator approval remain independent.

The optional face detector uses the existing model-source scope resolver. Its
explicit preflight seals the pinned local YuNet bytes and checks an isolated CPU
Python worker. AVO packages the worker code and schemas. A separate hashed wheel
list describes the qualified environment. Geometry association uses normalized
boxes and native source ticks in pure code. Ambiguity, missing detections and
sampling gaps require a new selection. Runtime readiness and observations are
separate from camera application or proof approval.

Face analysis binds the original stream, native clock origin, proxy digest,
detector identity and selected measurements in one immutable record. Pure timeline
code smooths its bounded trajectory and compiles it against one exact visible
source occurrence and BMap cue. Recorded hold or static fallback choices handle
uncertain output frames. The existing camera evaluator and native resampler consume
the compiled path and check crop margins and protected regions on every frame.
Proposal, application and proof admission verify the selected evidence. Historical
face records referenced by proposals or Animation survive reconstruction. The
linked map and storyboard read face readiness from metadata without running the
detector. Existing non-face moves retain their recorded options and cue clock.

For selected SFX, proof receipts bind the native combined sample peak and RMS
to the exact output window, candidate and mixed PCM. An explicit ducking review
margin adds a bounded, separate analysis pass on the prepared control signal
and post-duck effect. Timeline review verifies the overlapping sample range and
the frozen setting before deriving an attenuation suggestion. The analysis
never contributes samples to the proof output. Native PCM fixtures verify
bit-for-bit equivalence with the optional analysis on or off.

Explicit reference analysis shares the bounded display proxy and isolated CPU
vision runtime. It uses feature tracking without the face model, binds its
partial-affine estimates and residuals to actual adjacent native timestamps,
and exposes cut candidates and unmeasurable intervals separately. Reference
measurements and labeled contact sheets form an immutable inspection record
under the project. They enter editorial decisions through reviewed document
references and keep proof source admission independent.

Visual timing derives hold, reveal, fade and easing candidates from the sampled
frame grid. With an explicit audio selection, the media adapter measures energy
onsets on the original sample clock. The timeline may attach current prepared
word evidence from the same route. It validates the source, scope and retained
analysis before publication. These observations inform review and carry no
rendering or source-admission authority.

Reviewed reference decisions seal the selected measured aspects into a compact
project-only `ReferenceDescriptor`. Briefstart consumes that document through
its existing source loader and checks the inspection hash and project identity.
The direction layer has no dependency on the vision runtime or reference media.

Contextual asset review binds one motion proposal need, scoped local folders,
fingerprinted options and an optional prepared background. The image adapter
produces a numbered comparison sheet. Motion plan selection retains the chosen
round and revalidates its precise source before canonical application. The
storyboard bases declared readiness on a matching canonical cue fingerprint.
Library promotion and media admission keep their existing owners.

Spoken-note detection inspects prepared source evidence using an explicit
language and delimiter convention. The cutting store retains the immutable
report and separately tracks interpretation and speech choices. Iteration
context exposes accepted interpretations only to their owning stage and
rechecks the original source and transcript. Speech exclusion creates a
normal editorial cutting proposal under the current cutting policy.

The optional editor handoff assembles a bounded, original-source interchange
example from the current canonical contiguous or placed timeline. The native
command injects media inventory and the FCP7 XML adapter into the timeline
service. The immutable manifest retains exact occurrence clocks, audio frame
quantization, and affected ranges whose treatments stay in AVO. Returned XML
is saved verbatim and compared with the retained export and current timeline.
An explicit validation request can link a full-canvas generated alpha source
from a current immutable proof plan. The native adapter reuses the normal
generated-media admission checks and validates the editor transport copy against
every decoded RGBA frame. The manifest retains both media fingerprints, the
range, the generated receipt and the proof-plan identity for relinking.
That comparison records separate field proposals and conflicts for review.
Selected linked original-source trims become ordinary cutting proposals with
their existing preview and editorial approval. The route retains its exact
editor evidence, and ambiguous or unsupported fields stay available for manual
review.
Project-local target qualification binds operator observations and both XML
identities to the exact app, OS, profile and implementation. Production export
requires a qualified review reference that still verifies against its sources.
See [editor handoff](docs/editor-handoff.md).

The iteration ledger ties a proposed render workaround to the exact candidate,
its matching reproduction evidence, affected program windows and the observed
engine, runtime, profile and platform. Provider learning retains the summarized
defect. Workaround details stay in the originating project review.

Candidate craft review reads current BMap intent only after the proof
materialization and canonical hashes match the encoded candidate. Sampled
findings link to cues through cited frame numbers and half-open program
intervals. The review package preserves playback and listening requirements.
The wrap uses the approved master, candidate snapshot and retained ledger for
provider learning. Project-only records stay out of direction suggestions.
Provider animation decisions verify their own proposal and provider identity.

Camera movement, face anchoring, sound matching, reference analysis, spoken
notes/recovery and editor handoff are selected options resolved through existing
settings scopes and frozen requests. Preferences seed future work and cannot
reinterpret an active or approved edit. Existing canonical ownership, command
permissions, creator gates and source-only proof ancestry remain authoritative.

BMap owns camera cue timing; a strict versioned Animation extension holds only
relative behavior; Tracks identifies the original-source contribution. A new
proof v2 camera capability/implementation must be added to compiler, preflight,
executor and fidelity/lineage checks together. It transforms source picture
before independent overlays/captions. Legacy strategy/proof v1 remains supported;
old consumers fail closed on advanced behavior rather than silently ignoring it.
Because generic revision snapshots currently accept arbitrary objects, advanced
publication also needs an atomic Animation index-v2 reader-capability guard.
New readers support legacy/new indexes and validate advanced snapshots; old
index validators reject v2 before compiling. Default views never upgrade indexes.

Optional bounded CV/semantic adapters produce frozen source/model-bound evidence.
Direction stays document-only; renderer seeking starts no detector. A focused
read-only SFX catalogue reuses waveform/event-clock facts, keeps perceptual-marker
review separate from measurement cache, and never invokes footage move workflows.
Selected sound still becomes BMap/Tracks state through its current owners.

Editor handoff uses a bounded supported XML adapter with exact target-version
qualification and source/occurrence accounting; existing OTIO reader plugin
isolation remains intact. Returned edits are base/current/returned proposals,
with unsupported finishing preserved and conflicts reviewed before normal
activation. Export generation alone is not interoperability evidence.

Dependency direction remains CLI/MCP -> services/pure rules -> injected
media/model/format ports, with adapters registered at the boundary. No new
application framework, central state file, event bus, vector database or
repository-wide architecture refactor is planned. Reconstruction/inventory
must retain bounded selected authorial/source/rights/analysis/handoff/recovery
evidence and regenerate disposable views/indexes.

Implementation validation requires default/no-option and legacy compatibility,
pure frame/clock/merge rules, real encoded source-fidelity/audio checks,
native/MCP/package parity, existing full software-quality gates and actual
creator/target-editor acceptance. These remain future delivery gates.

The implemented preference boundary is `editing_craft.py`, reusing the existing
scoped settings merge and motion preference path/schema/CAS guards. Every supplied
scope is validated before merging; video defaults retain distinct provenance.
Typed run selections in `PipelineRunStore` preserve exact choices, direction and
available-head references without changing canonical state or transferring review.

`timeline/motion_review.py` reads available canonical snapshots and selected
context, including explicit absence. It does not construct the initializing BMap
or iteration-ledger services. Pipeline status, briefing and motion context expose
the same deterministic map/card view; published-report freshness is separate from
snapshot identity. Explicit publication writes immutable JSON/Markdown/HTML/CSS
under the external project's review tree, verifies matching bytes and containment,
and retains a historical report when heads race. Native motion authoring publishes
the derived review after a successful canonical write; presentation failure stays
visible and does not roll back the edit.

Focused tests verify partial/static views, exact identities, no default execution
or filesystem writes, request freezing, native/MCP parity, report tampering and
publication failure. These checks do not establish human suitability, target-editor
fidelity, optional model readiness or a finished master. See
[`docs/editing-craft.md`](docs/editing-craft.md) for the current interface.

### Explicit frame repetition in imported source placements

Placed imports can declare `pictureSampling: "repeat-2x"` on an individual
moving-picture mapping. The declaration is retained on the canonical placement
and compiled into the same source-layout graph for microproof and full render.
Source clocks are verified at half the program rate; trims must still land on
native source frames. Native execution repeats each decoded source frame twice
without changing wall-clock duration, audio samples, or placement boundaries.
Undeclared rate conversion, unknown sampling modes, still/audio sampling and
unverified variable-rate sources remain blocked.

Normalizer 2.1.0 binds the new admission semantics to fresh packets. Sampling
imports record `placed-sampling-1.0.0`; previous contiguous/placed capability
versions remain valid for their immutable canonical history. Prior packets are
not silently reinterpreted. The existing implementation fingerprint already
includes admission-layout rules, canonical compilation and native execution.
This extends the existing services and media adapter; no parallel timeline,
framework, or renderer abstraction is introduced.

Validation compares every repeated decoded frame and unchanged PCM, including
a microproof beginning on the second copy of a source frame, and a real encoded
30-to-60 fps trim. Synthetic activation and origin verification preserve the
new capability while historical import provenance stays supported. This is a
sampling capability, not qualification of Resolve transforms, titles, fades,
audio-tail policy, or a particular video's fidelity.
## Declared Resolve treatments

Placed CMaps can retain explicit picture geometry, alpha fades, native decoded
audio-tail gaps, and bounded static titles. Authorial title and font inputs are
separate from raw audiovisual inputs and are admitted to title placements
(or retained generator references in export-driven drafts);
contiguous CMaps retain their raw-only rule. The existing initial-cut compiler
and native placed proof adapter own execution. Titles use pinned local fonts
with inert text data; exported Fusion code is never executed.

The media adapter counts native audio samples using the existing bounded clock
scanner. Core admission compares these facts with explicit declarations before
creating a proposal. Disabled Resolve effects remain inert reference evidence;
unknown and enabled effects remain blocking. All original and authorial inputs
are fingerprinted and revalidated before proof publication. Native frame/PCM
tests and canonical admission tests qualify the supported subset; a synthetic
pass does not qualify an individual Resolve export or grant creator approval.

## Export-driven Resolve draft import

Ordinary pipeline and CLI preparation now derive a placed draft from OTIO,
original media and an optional paired DRT. `import_auto` orchestrates existing
probe/admission ports; the bounded `resolve_sidecar` media adapter reads sequence
settings and literal static title metadata without starting Resolve or executing
Fusion. Dependency direction remains entry points -> timeline services/pure rules
-> injected media ports. No second timeline owner or renderer is introduced.

`resolve_export` translates complete supported static parameter sets and retains
all other effects as inert canonical `resolveEffects`. Unsupported generators
retain their authorial export plus payload. An original whose packet clock is
unverified can remain in an export-driven draft with explicit unverified clock
metadata. Structural readiness permits normal explicit draft selection after
Sync review; render readiness independently rejects active unresolved treatments,
generators and video clocks. Both the initial-cut request builder and proof-plan
compiler enforce that guard. Explicit source-only and declared-treatment routes
remain strict, and historical packets are not rewritten.

Normalizer 2.6.2 and `placed-export-driven-1.0.0` bind these semantics to new
immutable packets. Exact local reference identity, source fingerprints, prohibited
proof ancestry, provider isolation and optimistic activation locks still apply.
Regression coverage exercises default pipeline/CLI preparation, opaque retention,
clock warnings, strict-route compatibility, and refusal to render unresolved
drafts. An actual export trial is staging-only and grants no creator approval.

### Imported approximation previews and bounded picture end gaps

Normalizer 2.7.0 adds explicit `pictureEndGapFrames` for one to three missing
presentation positions immediately before the final packet. The native clock
verifier requires an otherwise exact complete grid and a grid-aligned final PTS;
interior irregularities and larger gaps remain unsupported. Strict verification
is unchanged unless the bounded policy is requested. Canonical admission and
native execution verify the exact declared gap and use timestamp-based holds
before source trimming. `placed-end-gap-1.0.0` identifies the new contract.

An explicitly authorized `importApproximation` records every unresolved effect
pointer/name and requires `previewOnly: true`. Both canonical compilation paths
reject stale omissions and refuse to waive unverified clocks or opaque generated
sources. The existing preview-only materialization guard prevents promotion into
a full proof. Original effect payloads and canonical edit intent remain intact;
the preview is a supported-treatment projection, not fidelity certification.

Placed microproof execution omits pictures outside the requested window and
stores only each picture's intersection with that window. Sampling, transforms
and fades run on the original clip clock before extraction, preserving fade
phase, exact repetition and qualified end-gap holds without input seeking.
The compositor renders only the window's local clock; privacy masks still
evaluate absolute program frames. This avoids writing, decoding and compositing
unneeded picture prefixes. Source admission, fingerprint checks, the canonical
graph and continuous audio mix remain unchanged. Encoded frame/PCM and
micro/full comparisons qualify the optimization; original media is never
rewritten.

Placed CMap layouts can declare `privacyMasks`: bounded opaque black rectangles
on the canonical canvas with exact inclusive-start/exclusive-end program frames.
Schema and semantic admission reject duplicate IDs, fractional coordinates,
out-of-canvas regions and out-of-program intervals. The source-layout compiler
freezes these decisions into its graph; import graph preservation rejects
dropped or moved masks. Native FFmpeg draws them after all picture layers and
fades, before window extraction, rounding scaled edges outward. Masks have no
fade or opacity option and do not change source routing, audio or timing.
Implementation hashing invalidates older proof execution locks when this
renderer changes. Native full/micro frame and PCM comparisons cover privacy
through imported overlay fades.

Placed audio clips may explicitly set `audioPeakCeilingDbfs` (-12 to -1 dBFS).
The source compiler binds it to the clip's gain operation. Native validation
rejects unbounded values and applies the existing limiter with compensated
lookahead after gain and before window extraction. Processing therefore retains
the full node history for identical full/micro samples; other audio nodes and
legacy gain-only calls remain unchanged. This is an opt-in sample-peak ceiling,
not a true-peak delivery certificate. Encoded true peak requires separate QC.
The shared limiter formatter is included in implementation fingerprint locks.

### Bounded native placed rendering

Full placed proofs use a private streaming executor behind the existing render
port. Each admitted placement has one persistent decoder with the same complete
sampling, transform and fade filters as scoped proofs. Small raw BGRA windows
enter the existing compositor and absolute-frame privacy masks. Generated assets
remain continuous inputs to one final encoder, preserving their local phase.
The canonical graph, source admission and public CLI/schema remain unchanged.

The native audio graph is mixed once before picture decoding. Source PCM scratch
is released before picture work, and the exact resulting stereo mix supplies the
continuous encoder. A private in-process observation boundary permits a job to
qualify that mix before expensive picture work without modifying it.

Picture windows are capped at 60 frames and 6 GiB of active scratch. Admission
reserves the larger of the temporary source PCM plus complete mix, or the
12 GiB candidate allowance plus complete mix, with 2 GiB of free headroom in
each phase. Native source-PCM cleanup must succeed before picture begins.
The picture phase rechecks actual available space with its already allocated
mix, accounting for admitted layer dimensions and current disk availability.
Consumed job-owned windows are
removed immediately. Child errors, short/extra decoder output, frame mismatch,
disk exhaustion and changed source fingerprints prevent publication. Diagnostics
remain separate from ephemeral media. Publication follows validation and scratch
cleanup, and existing project media is retained.

Generic FFmpeg integration fixtures compare every decoded RGBA frame and stereo
PCM sample with scoped legacy rendering across layers, titles, privacy edges,
fades, repeated frames, generated animation phase and EOF failures. Unit tests
cover process cleanup, partial pipes, storage accounting and failed publication.
The new executor and stream utilities participate in implementation fingerprints.

HyperFrames capture copies also reset eligible composition render trees after
native pending-seek completion, before taking a screenshot. Identical final animation
state can otherwise retain history-dependent Chromium paint-cache rounding.
The capture-only hook hides each top-level composition, forces layout, restores
the exact prior inline-style attribute, and forces final layout. It preserves
the native completion callback's arguments, receiver, result and errors. The
authoring project and its animation values remain unchanged. Roots with browser
animation objects or CSS animation/transition declarations retain the existing
capture path, avoiding animation restarts when rebuilding layout. This compatibility
policy is recorded in the generator environment for the qualified installed
runtime; changing it invalidates previous generated assets. Independent,
reverse-order and production captures still require exact decoded pixel equality.

Normal SDR proof encoding converts the composited full-range RGB picture to
limited-range BT.709 YUV420P and declares matching matrix, primaries, transfer
and range metadata in H.264. Untagged HD playback can otherwise select a
different matrix from the RGB-to-YUV conversion and shift the approved colours
between players. This is an explicit encoding contract, not a creative grade.
Lossless FFV1/BGRA conformance output remains unchanged. Runtime fixtures verify
colour patches, stream metadata, frame timing and audio independently; browser
qualification checks the same encoded frames against canonical RGB references.

An explicit `h264_nvenc` ProofPlan output uses NVIDIA H.264 encoding with the
existing continuous encoder boundary. Its quality settings are p5/HQ, VBR,
CQ 19, 12 Mb/s target, 18 Mb/s maximum, a 36 Mb buffer and High profile.
Source decoding, placement filters, compositing and the continuous audio graph
retain their existing owners. CPU H.264 and lossless FFV1 arguments are unchanged.
There is no implicit hardware selection or CPU fallback. Encoder settings are
part of the implementation lock, so switching encoders requires fresh native
windows and final-file review. See [GPU proof encoding](docs/gpu-proof-encoding.md).

Generated-media admission requests historical-output inventory lazily, after its
complete contributor and generated-input closure is available. A conservative
byte-size filter avoids reading historical files that cannot equal any inspected
input. Missing, stale or incomplete input sizes, including one-shot ancestry
iterators, retain full inventory. Matching files are freshly hashed in an
independent stage on every admission; retained materialization hashes remain
unconditional. This adds no negative-evidence cache or source-identity shortcut.
The three HyperFrames generator implementations and their existing bindings are
unchanged. See [generated-media admission](docs/generated-media-admission.md).
