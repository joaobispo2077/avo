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


## Motion engine selection and code-drawn capture (feature 012)

HyperFrames remains the default. The pure shared motion policy resolves invocation, pinned run, project/video, provider/channel and global preferences, in that order. Strict saved IDs are hyperframes, remotion, and code-drawn; Remotion retains its existing unsupported execution adapter. A new default never rewrites a recorded animation revision or creator decision. Explicit new engine/source authoring uses existing revision invalidation. Installed motion and pipeline routers resolve current no-framework intent before loading engine-specific skills.

The advanced code-drawn route is model-neutral Canvas, SVG, or optional pinned standalone p5.brush. The shared motion module owns preferences, source contracts and canonical coordination; motion_runtime owns read-only optional-runtime discovery. The motion adapter owns Playwright/Chromium capture, local allowlisting, independent arbitrary-frame checks, PNG capture and FFmpeg lossless silent FFV1/BGRA publication. Playwright's pinned driver, internal Node and templates ship in the onedir engine; managed browser binaries, FFmpeg and optional local brush provisioning remain explicit runtime installation. There is one packaged template owner.

Canonical authority flows manifest/source snapshot → logical Animation + Tracks source reference → original input lock → generated receipt → frozen ProofPlan. CMap/Sync approvals and current BMap/Tracks/Animation dependencies are derived from real workspace stores. BMap/Tracks own timing and placement; source strategy has no clock and cannot point forward to output hashes. The injected outer composition observes the actual browser/driver/graphics/encoder environment. Timeline services consume observations or a trusted verifier callback and import no renderer. Direct and recursive admission reject stale bytes, bindings, implementations and prohibited output ancestry even when a file is renamed as a font or dependency. Standalone capture conveys no canonical admission or creator approval.

The existing FFmpeg ProofPlan path handles generated-clip and overlay-video. It freezes receipt, lock, frame range, placement and stable z-order; partial proofs retain the original local-frame phase across cuts. Original source audio keeps its canonical graph and envelope. Unsupported mixing/event envelopes fail before output. Explicit FFV1/PCM Matroska conformance uses this same graph for exact decoded pixel and sample checks; normal delivery encoding stays separately checked. Reconstruction retains the complete declared source/dependency/receipt/lock closure and can remove only regenerable output under existing cleanup authority.

Validation is recorded in specs/012-code-drawn-motion/validation.md: schema/legacy compatibility, seven installed agent profiles, source and extracted native capture, current-environment admission, physical alpha/phase/audio checks, and source-only rematerialization. Local execution identifies Windows AMD64 and its actual graphics renderer; configured Linux/macOS lanes are not claimed as executed locally. See [code-drawn motion](docs/code-drawn-motion.md).

The provider settings validator retains its existing beside-launcher compatibility lookup. Both binary build scripts copy only `providers/avo.provider.schema.json` there before archiving; no provider identities, footage paths or global preferences are packaged. An explicit external `AVO_ROOT` remains responsible for its standard public-schema tree. Scoped writes are validated before replacement and retain unrelated settings.

Compatibility also preserves generic projects whose inferred provider has no manifest: absent provider preferences inherit global/default settings. Explicit provider targets and existing malformed manifests still fail validation; inspection does not create provider files. This keeps optional creative briefing and raw project intake usable without broadening preference writes.

Native proof review shares the existing cut-lineage dispatcher and source-fidelity adapter. Later checkpoints use the generic persisted ProofPlan verifier, while cut-proof retains its strict checkpoint verifier. Native final fidelity derives an explicit `nativeBasis` from current plan/source/generated provenance, microproof gate and actual FFprobe observations; it never fabricates legacy delivery-policy/picture-lineage envelopes. Its verified scope is progressive 8-bit SDR with the executor's supported frozen graph, exact geometry/rational rate/frame count/codecs/pixel format and stereo audio/duration. Untagged 8-bit source is interpreted as SDR; HDR/wide-gamut/high-bit-depth/interlaced or unsupported graphs remain blocked. Existing assembly evaluation and human, transcript, rights/accessibility and Watch authority are unchanged.

Regression revalidation uses the native dependency dispatcher to verify native
ProofPlan source aliases and their aggregate raw hash. Legacy assembly
`rawFingerprints` retain their separate compatibility path. Neither format skips
current-input, source-byte, graph or microproof validation. Coverage includes
native cut regression approval and rejection of altered source bytes and locks.

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
events must identify their exact declared node and onset; unsupported effects,
missing events and clock mismatches fail closed. The mix adapter accepts only
finite ranges, literal gain, bounded fades and declared sidechain ducking. A
lossless same-plan dialogue intermediate supplies the lead without reading an
earlier proof. Float PCM preserves headroom until the single final audio encode.
Independent finite picture/audio inputs reach EOF so a video frame-count stop
cannot discard the last PCM packet of a microproof.

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

