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
