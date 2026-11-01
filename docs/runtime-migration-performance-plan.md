# AVO performance research: measured baseline and migration plan

Follow-up: [measured Rust/Go/C candidate results](runtime-migration-candidate-results.md) now add actual native prototypes, complete accounting/CLI comparisons, regressions, and an encoded-proof comparison. The tables below retain the earlier baseline/planning evidence; use matched comparisons in the follow-up for candidate gains.

Measured and researched 2026-10-30. Priority: performance. First implementation: hybrid quality checking, before migrating product code.

The current measurements identify worthwhile experiments, but do not establish that Rust, Go or C is fastest for AVO. A selective Python/native approach is the first hypothesis because it can target expensive responsibilities while retaining existing connectors. The full [implementation plan](../specs/014-runtime-migration-feasibility/plan.md) and [research decisions](../specs/014-runtime-migration-feasibility/research.md) define the next work.

## Real numbers from the current structure

These are observed current-source values, not estimates. Environment: Intel Core i7-11800H, 16 logical CPUs, Windows build 26200 x64, .venv Python 3.11.3, NumPy 2.4.6, jsonschema 4.26.0, faster-whisper 1.2.1. Fixtures are synthetic; file caches are warm. Source HEAD is `72dc80ff9bad4ff943c828ae123cd70551d70d70` with unrelated local modifications captured in source manifests. This is not a clean released-binary baseline.

| Work in the current product                | Scale / condition                  |     Median |     Observed range | Measured runs |
| ------------------------------------------ | ---------------------------------- | ---------: | -----------------: | ------------: |
| Canonical document serialization + SHA-256 | 1,000 timeline-like items          |   0.959 ms |     0.918–1.761 ms |            30 |
| Same canonical hash                        | 10,000 items / 0.83 MB             |  12.396 ms |   10.980–18.066 ms |            30 |
| Same canonical hash                        | 100,000 items / 8.39 MB            | 131.088 ms | 104.178–185.375 ms |            30 |
| Source fingerprint                         | 256 MiB synthetic file, warm cache | 322.568 ms | 298.529–594.291 ms |            30 |
| Cost report                                | 1,000 observations                 |  52.314 ms |   46.197–67.532 ms |            30 |
| Cost report                                | 10,000 observations                | 328.396 ms | 270.194–477.970 ms |            30 |
| Cost report                                | 100,000 observations / 20 batches  |    4.965 s |      3.563–7.660 s |             5 |
| Fresh Python process, no AVO work          | Warm executable/files              |    89.5 ms |      70.6–152.2 ms |            30 |
| Engine dispatcher help                     | Fresh process, warmed files        |   261.5 ms |     233.2–550.8 ms |            30 |
| Timeline CLI help                          | Fresh process, warmed files        |   682.1 ms |   554.7–1,520.5 ms |            30 |
| Resolve checkout runtime                   | Fresh process, warmed files        |   291.8 ms |     238.3–564.6 ms |            30 |

Short workloads had five warmups. The expensive 100k cost report used one warmup and five timed runs under a bounded-run exception. Its broad range makes the median provisional; no confident p95 is claimed. Core operations ran sequentially; launch cases were interleaved round-robin in a later non-overlapping timing window. Each output was checked. These observations measure the named operation, not a complete video production.

The startup difference suggests testing import/parser work and command batching as Python controls. The two help commands expose different behavior, so their timing difference is not a measured replacement improvement.

## How much faster could selected work become?

Separate diagnostic profiles show where time went. Profiles add overhead, so their fractions are experiment-selection proxies rather than exact uninstrumented shares.

| Candidate responsibility      | Current evidence                                                                              | What it means for performance                                                                                                                       |
| ----------------------------- | --------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| Canonical serialization       | About 0.144 s of a 0.151 s instrumented 100k-item hash; SHA-256 about 0.006 s                 | Most of this operation's cost is producing canonical bytes. A replacement must preserve exact bytes and rejection behavior.                         |
| Cost aggregation              | `_aggregate` about 1.732 s of 6.259 s instrumented report time, approximately 27.7% inclusive | This is a plausible coarse pilot with seconds of potential benefit on large reports. Conversion and integration costs still count.                  |
| Report JSON work              | Encoding/decoding self times about 1.205 + 0.837 s, approximately 32.6% of the same profile   | Another hypothesis; it overlaps higher-level responsibilities and must not be added to aggregation's share. Integrity validation cannot be omitted. |
| Fingerprint Python loop alone | About 0.016 s self time; native SHA-256/read work approximately 95%                           | Deleting only the wrapper's work has about a 1.05x ceiling for this operation. Read strategy is a separate optimization.                            |

For a concrete planning scenario, suppose aggregation really consumes 27.7% of uninstrumented report time. The table assumes the rest is unchanged and adds no boundary overhead:

| Assumed future aggregation speed | Calculated full report time from 4.965 s |      Time saved | Overall speedup |
| -------------------------------: | ---------------------------------------: | --------------: | --------------: |
|                               2x |                                  4.277 s | 0.688 s / 13.9% |           1.16x |
|                               5x |                                  3.865 s | 1.100 s / 22.2% |           1.28x |
|                              10x |                                  3.727 s | 1.238 s / 24.9% |           1.33x |
|        Instantaneous aggregation |                                  3.590 s | 1.375 s / 27.7% |   1.38x ceiling |

These are calculations, not Rust/Go/C timings. A 20 ms integration cost would add 20 ms to each projected total. The true gain can be lower if profile fractions change or data conversion is expensive.

For the requested 20% native / 80% Python split, source lines are not the relevant percentage. With 10x acceleration of a portion taking 20% of runtime, the whole workflow becomes 1.22x, saving 18% of elapsed time. If the portion takes only 5% of runtime, the gain is 1.047x, saving 4.5%. A small code fraction can be valuable only if it owns a large, replaceable runtime fraction.

## A measured control before changing language

A follow-up used five warmup pairs and thirty alternating pairs on the same 256 MiB warm-cache input:

| Observation                                            |         Value |
| ------------------------------------------------------ | ------------: |
| Current AVO fingerprint median                         |    292.346 ms |
| Existing Python `hashlib.file_digest` primitive median |    211.384 ms |
| Median paired time reduction                           |        26.05% |
| Median paired speedup                                  |        1.352x |
| Median paired absolute saving                          |     77.232 ms |
| Pairs where the primitive was faster                   |       30 / 30 |
| Descriptive paired bootstrap 95% reduction interval    | 25.33%–28.10% |

This is real measured evidence for a buffering/read-strategy investigation without a new language. The primitive only returns a digest; it does not implement the complete AVO fingerprint/cache/stage/final-verification contract. It cannot be adopted on this timing result alone. The interval describes these finite samples, not a guarantee on other files, disks or cold storage. Independent-block timing above and paired timing here are different runs, not contradictory results. Do not subtract unpaired medians to calculate the paired saving.

## Native engines already do substantial work

A second local experiment encoded the same synthetic eight-second 640×360/30fps input using FFmpeg 7.1.1, libx264 veryfast, CRF 23, two encode threads and 48 kHz AAC:

| Invocation                                           |   Median |          Range | Runs |
| ---------------------------------------------------- | -------: | -------------: | ---: |
| Direct FFmpeg with progress output captured          | 415.2 ms | 346.8–522.7 ms |    5 |
| Existing AVO `run_ffmpeg_progress`, already imported | 373.8 ms | 351.8–498.3 ms |    5 |

Both produced byte-identical 861,819-byte output with 240 video frames and 48 kHz audio. The short-run distributions overlap; the wrapper's lower median is not evidence that wrapping accelerates FFmpeg. This observation cannot resolve a useful wrapper-only gain. It excludes Python import/launch, source-admission, canonical proof planning, visual review and full motion work; it is not a complete rendering benchmark.

The external evidence reinforces the need to separate language from configuration. For thirteen minutes of audio, the faster-whisper maintainer reports the following under its published version/hardware settings:

| External experiment                                     |   Reported times | Relevant tradeoff                                                                       |
| ------------------------------------------------------- | ---------------: | --------------------------------------------------------------------------------------- |
| Large-v2 GPU fp16, faster-whisper versus whisper.cpp    | 63 s versus 65 s | Different inference implementations; the native-facing alternative was not faster here. |
| Same faster-whisper GPU benchmark, batch 1 versus 8     |      63 s → 17 s | 73.0% less time, VRAM 4,525 → 6,090 MB (+34.6%).                                        |
| Small-model CPU fp32, faster-whisper versus whisper.cpp |    157 s → 125 s | 20.4% less time; backend difference, not an AVO language result.                        |

GPU benchmark: RTX 3070 Ti 8 GB, CUDA 12.4, beam five; CPU benchmark: i7-12700K, eight threads, beam five. Versions include faster-whisper v1.1.0 and whisper.cpp v1.7.2. These are externally reported measurements, not local observations or future AVO promises. [Maintainer benchmark](https://github.com/SYSTRAN/faster-whisper#benchmark).

## Which migration option deserves the first experiment?

| Option                                           | Performance case to test                                                   | Cost/constraint                                                                     | Current conclusion                                                       |
| ------------------------------------------------ | -------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| Improved Python using existing native primitives | Avoid repeated work, imports, copies and unnecessary per-item calls        | Must preserve all validation and final rechecks                                     | Mandatory control; could win without a language migration.               |
| Python + coarse Rust component                   | Move a profiled batch responsibility while retaining Python connectors     | Conversion, ABI, wheels, frozen artifacts and error parity                          | First integration hypothesis after gate; no measured candidate gain yet. |
| Python + Go worker                               | Batch substantial independent work behind an existing process boundary     | Process/serialization lifecycle; cgo adds native build constraints                  | Useful challenger if work is coarse enough.                              |
| Python + C component                             | Accelerate the same bounded responsibility close to an existing native API | Ownership, allocation failures, overflow, sanitizer/static checks                   | Include as challenger; pure C is not assumed fastest or cheapest.        |
| Full Rust, Go or C AVO runtime                   | Could reduce Python-owned work across commands                             | Largest connector/contract/packaging migration; external engines still consume time | No evidence yet for a whole-product speedup or practical winner.         |

Mechanisms and constraints: [PyO3](https://pyo3.rs/v0.30.1/), [Maturin distribution](https://www.maturin.rs/distribution.html), [Go cgo](https://pkg.go.dev/cmd/cgo), and [CPython C extensions](https://docs.python.org/3.11/extending/extending.html). These establish feasibility paths; they do not benchmark AVO.

## Execution-mode coverage

| Mode/profile                                     | Current evidence                                           | Next measurement                                                                                         |
| ------------------------------------------------ | ---------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| Windows source CLI/modules                       | Startup and core operations measured above                 | Integrated representative operation, resource limits and paired controls.                                |
| Installed onedir engine                          | Current packaging inspected; no matching release benchmark | Exact installed-artifact startup, size, install and representative work.                                 |
| Editable install / npm / agent entry points      | Source/runtime routes inspected                            | Separate wrapper cost and identical task behavior. Agent guidance itself is not executable code to port. |
| Local stdio MCP                                  | Current in-process CLI bridge inspected                    | Protocol, continuity, cancellation and representative tool latency on each runtime.                      |
| Background/library workers                       | Current dispatch and ownership inspected                   | Worker lifecycle, sustained work, cancellation, peak process-tree resources.                             |
| Prepared offline / CPU / GPU                     | Dependency boundaries inspected                            | Exact model/browser/driver prerequisites, load time and sustained operation.                             |
| macOS / Linux / WSL and architecture variants    | Configured paths/build targets inspected                   | Actual machine/artifact runs; no certification inferred from CI configuration.                           |
| Container, package-manager, remote/cloud options | Proposed delivery options only                             | Feasibility screen; no hosted service is being built by this study.                                      |

No complete video workflow percentage, native artifact size, installation speedup, GPU migration gain or cross-platform language ranking is measured yet.

## First implementation: hybrid quality gate

The current receipt source fingerprint covers Python files. First add native source/build/artifact identity, exact baseline/candidate contracts, failure controls, per-language checks and performance evidence to the existing Software quality and local quality paths. Keep current thresholds and historical report definitions. An empty verified native inventory is not applicable, not a native PASS.

After that gate is validated, run the candidate comparison. Proposed adoption targets are at least 20% lower affected-operation median, practical savings of 10 ms per interactive call or 1 s per sustained workload, 95% paired lower speedup bound above 1.05x, no more than 5% integrated regression, and a preregistered memory ceiling. These are engineering targets, not forecasts. No production migration starts in this planning turn.

## Raw evidence and reproduction

- [Core measurement notes and profiles](../specs/014-runtime-migration-feasibility/core-measurement-notes.md).
- [Core raw samples](C:/Users/vitor/.codex/visualizations/2026/10/30/01a18ed7-d1f7-7c93-a58f-b22d832f3368/avo-runtime-research/core/20261030T222957Z-f58ad155/measurements.json).
- [Paired fingerprint control samples and uncertainty](C:/Users/vitor/.codex/visualizations/2026/10/30/01a18ed7-d1f7-7c93-a58f-b22d832f3368/avo-runtime-research/core/20261030T223701Z-paired-fingerprint-f4b06cc6.json).
- [Launch/media protocol and source hashes](C:/Users/vitor/.codex/visualizations/2026/10/30/01a18ed7-d1f7-7c93-a58f-b22d832f3368/avo-runtime-research/launch-media/protocol.json).
- [Launch raw samples](C:/Users/vitor/.codex/visualizations/2026/10/30/01a18ed7-d1f7-7c93-a58f-b22d832f3368/avo-runtime-research/launch-media/startup-results.json).
- [Media raw samples and output hashes](C:/Users/vitor/.codex/visualizations/2026/10/30/01a18ed7-d1f7-7c93-a58f-b22d832f3368/avo-runtime-research/launch-media/media-results.json).
- [Validation/reproduction guide](../specs/014-runtime-migration-feasibility/quickstart.md).

Source data, generated inputs, research scripts and large artifacts remain external. Planning documents define reusable commands to build later. Memory-service access was unavailable; no retrieved memory decision was assumed. Process-tree RSS/GPU/energy observations and real migrated implementations remain missing, so these discovery numbers cannot qualify a release.
