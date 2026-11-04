# AVO runtime migration research brief

Date: 2026-10-30. Status: initial specification discovery, followed by completed planning and local baseline discovery.

The owner subsequently authorized deeper isolated research. [Candidate results](runtime-migration-candidate-results.md) now provide measured native integration gains and regressions. Production migration and the hybrid quality gate remain unimplemented.

The question is whether AVO should stay in Python, move selected responsibilities
to Rust, Go, or C, or fully migrate its own executable logic. The decision must
follow measured AVO workloads, connector parity, delivery requirements, and the
cost of maintaining the result. The initial specification pass selected no language.
The subsequent [performance plan and baseline report](runtime-migration-performance-plan.md)
adds actual current-source timings and calculated scenarios. No Rust/Go/C migration
comparison or production quality-gate implementation is claimed as completed.

The [feature specification](../specs/014-runtime-migration-feasibility/spec.md)
defines the complete study and acceptance conditions.

## Repository observations

Discovery used checkout HEAD `72dc80ff9bad4ff943c828ae123cd70551d70d70` on
`feature/avo-ways`, with unrelated staged and unstaged changes in the binary
workflow, architecture document, media/QC implementation, and tests. This is not
a clean released-artifact baseline. Actual experiments must capture the precise
tested tree and artifact identities again.

| Observed boundary                     | Current repository evidence                                                                                                                    | Consequence for the study                                                                                                                                                                                                                                                |
| ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Product architecture                  | [ARCHITECTURE.md](../ARCHITECTURE.md), [.importlinter](../.importlinter)                                                                       | Modular monolith with adapters at external boundaries; compare migration of actual responsibilities and preserve existing import/authority contracts.                                                                                                                    |
| Installed versus repository execution | [consume_mode.py](../src/avo/consume_mode.py), [install guide](install/README.md)                                                              | Checkout detection, explicit overrides, and installed launcher are distinct paths; agent skills are guidance over those runtimes.                                                                                                                                        |
| Unified engine and stage commands     | [engine_cli.py](../src/avo/engine_cli.py), [package configuration](../pyproject.toml), [npm wrappers](../package.json)                         | Test startup and real command work separately; preserve direct module entry points and worker dispatch.                                                                                                                                                                  |
| Packaged engine                       | [avo.spec](../packaging/avo.spec), [Windows build](../scripts/ci/build-engine.ps1), [build workflow](../.github/workflows/engine-binary.yml)   | Current product is a PyInstaller application folder/archive with an interpreter, not a literal single native file. The inspected working workflow configures Windows x64, macOS arm64, and Linux x64; this does not prove published or successfully exercised artifacts. |
| External dependencies                 | [dependency manifest](../config/avo.dependencies.json), [package configuration](../pyproject.toml), [install guide](install/README.md)         | Media processing, inference, visual review, motion, and managed browser resources need separate attribution and packaging coverage.                                                                                                                                      |
| Local MCP                             | [bridge.py](../src/avo/mcp/bridge.py), [MCP guide](avo-mcp.md)                                                                                 | Current bridge invokes CLI operations in-process and captures output. A rewrite must assess more than server launch or tool enumeration.                                                                                                                                 |
| Routing and integration status        | [registry.py](../src/avo/adapters/registry.py)                                                                                                 | Distinguish implemented adapters from stubs and paid routes; assess capabilities rather than library-name similarity.                                                                                                                                                    |
| Existing performance evidence         | [timeline tests](../tests/test_timeline_performance.py), [cost tests](../tests/test_cost_performance.py), [library guide](library-organize.md) | Reuse workload knowledge, but tests with thresholds and earlier external measurements do not establish current cross-language results.                                                                                                                                   |
| GPU and alignment boundary            | [GPU execution guide](cutting-gpu-execution.md)                                                                                                | Device, precision, external alignment environment, model readiness, and serialized GPU use are independent experimental conditions.                                                                                                                                      |

Existing [consume-mode research](consume-modes-research.md) and
[binary research](single-binary-research.md) provide historical context. They
predate the current unified dispatcher and packaging changes; their statements
about missing entry points or prospective builds must not be copied as current
facts. No production code or architecture was changed for this brief.

The current project's ai-memory search was attempted through its local CLI;
the service was unavailable, including an upstream connection failure. No saved
memory finding was used or inferred. Repository inspection continued independently.

## Can AVO be approximately 20% Rust and 80% Python?

Yes, the integration model exists: PyO3 supports Python extension modules written
in Rust and embedding Python in a Rust program. That establishes an available
mechanism, not AVO compatibility, performance, or a recommended split.
[PyO3 documentation](https://pyo3.rs/)

The relevant research question is which small set of responsibilities consumes
enough replaceable time to justify the extra build and integration burden. The
maintained-code fraction and runtime fraction must be reported separately. A
native extension would still retain Python; a launcher embedding or invoking
Python would also retain it. This is a consequence of the proposed boundary,
not evidence for a Python-free product.

The theoretical ceiling for an unchanged serial workflow is
`overall speedup = 1 / ((1 - f) + f / s)`, where `f` is the measured fraction of
elapsed work improved and `s` is that part's speedup. As an illustrative
calculation only, improving a part that takes 20% of runtime by 10 times yields
about 1.22 times overall speed, or 18% less elapsed time. It says nothing about
migrating 20% of source lines. The model assumes unchanged remaining work and no
new boundary overhead; actual integrated measurements are required.

## Primary-source entry points

Sources were accessed on 2026-10-30. These establish research starting points;
the study must pin the actual tested versions and verify the capabilities AVO
uses before claiming compatibility.

| Subject                    | Primary evidence                                                                                                                                                         | Question still requiring AVO evidence                                                                                                                                      |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Rust/Python coexistence    | [PyO3 guide](https://pyo3.rs/) documents extension modules and embedding.                                                                                                | Which profiled responsibility benefits after conversion, copying, error handling, and invocation costs?                                                                    |
| Native module distribution | [Maturin distribution guide](https://www.maturin.rs/distribution.html) describes platform compatibility and linked-library considerations.                               | Can source installs and frozen artifacts include the same native component on required targets, including offline use?                                                     |
| Go/native integration      | [Go cgo documentation](https://pkg.go.dev/cmd/cgo) documents C interoperability and the additional cross-compiler requirement when cross-compiling with cgo.             | Which connectors need native bindings; what build, memory, invocation, and deployment costs follow?                                                                        |
| C/Python coexistence       | [CPython 3.11 extension guide](https://docs.python.org/3.11/extending/extending.html) describes C extension modules and their interpreter-specific interface.            | Which useful components can be bounded safely, and what compatibility, ownership, and error-path work is necessary?                                                        |
| Existing speech backend    | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) uses [CTranslate2](https://github.com/OpenNMT/CTranslate2), whose implementation offers C++ and Python APIs. | How much speech time is AVO-owned overhead, and would changing a wrapper affect total time or require a different backend?                                                 |
| MCP ecosystems             | The protocol organization maintains [Rust](https://github.com/modelcontextprotocol/rust-sdk) and [Go](https://github.com/modelcontextprotocol/go-sdk) SDK repositories.  | Do the pinned SDKs support the exact protocol, structured results, request continuity, cancellation, and gate behavior used by this checkout? Assess C support separately. |
| Existing frozen delivery   | [PyInstaller operating mode](https://pyinstaller.org/en/stable/operating-mode.html) describes collecting the interpreter and dependencies, with target-specific builds.  | What are current AVO artifact size, startup, installation, and resource figures, and which external tools remain necessary under each candidate?                           |

Existence of a language SDK is not connector parity. Existing native inference
does not prove Python overhead is negligible. Both are hypotheses to resolve by
profiling and representative integration checks.

## Expected decision evidence

The study will produce a mode/platform matrix, dependency and connector register,
profiled baseline, bounded comparable prototypes, measured hybrid integration,
raw observations with reproduction instructions, effort/value ranges, and a
decision report under `docs/`. It will distinguish the fastest measured option
from the most practical migration and permit a no-migration conclusion.

The full feasibility study is complete only after those acceptance conditions are
verified. The [plan](../specs/014-runtime-migration-feasibility/plan.md) now places
hybrid quality checking before production migration. The baseline report supports
experiment selection; complete candidate qualification remains future work.
