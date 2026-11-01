# What a full Rust AVO port could gain

Follow-up: [integrity-check measurements](integrity-check-performance-research.md) test current pre-render preflight directly, including Rust hashing and Python experiments that reduce repeated schema setup and parallelize independent hashes.

Date: 2026-10-30, America/Sao_Paulo. Scope: additional isolated research, with production migration still unapproved and unimplemented.

Full Rust has a higher potential ceiling than the earlier hybrids because it can remove Python startup, object handling and application loops together. To test that distinction, this pass built a standalone Rust read-only reporting operation with no Python interpreter, extension or fallback in its execution path. The complete AVO product has not been ported.

## Actual no-Python measurements

These are matched fresh-process measurements on the same Windows i7-11800H reference machine, using the current Python accounting operation as the reference. Both programs read the same immutable cost-store files, verify batch integrity and video identity, resolve observations, calculate tokens and exact amounts, produce breakdowns/watermarks/membership, and emit the same structured report for the supported inputs.

| Report scale         | Current Python | First standalone Rust version | Speedup | Less elapsed time |
| -------------------- | -------------: | ----------------------------: | ------: | ----------------: |
| 1,000 observations   |     522.558 ms |                     44.431 ms |  11.76x |             91.5% |
| 10,000 observations  |     739.269 ms |                    267.104 ms |   2.77x |             63.9% |
| 100,000 observations |        4.614 s |                       2.976 s |   1.55x |             35.5% |

The two smaller cases used five warmups and 30 interleaved measured fresh processes per implementation. The large case used one warmup and seven measured processes under an expensive-run exception. Every report was compared in full against the Python result. Filesystem caches were warm; these are not OS cold-cache or clean-install results.

The Python reference invokes the existing store/report operation through a thin process driver. This comparison is not the full AVO CLI parser/project-context path and must not be mixed with the earlier hybrid CLI timings.

Memory did not improve uniformly. Median peak process working set was 60.6 → 18.1 MB at 1k observations, 85.5 → 100.2 MB at 10k, and 427.0 → 712.4 MB at 100k. The first Rust version used generic JSON values and deep-copied batch payloads for integrity hashing. That implementation was faster at 100k but used about 67% more peak working-set memory.

This is evidence that removing Python can help; it also shows that a mechanical dictionary-to-generic-JSON translation does not automatically make Rust memory-efficient. Ownership, data layout and repeated work still need design and measurement.

## Matched optimization test at 100k observations

A second Rust version borrows immutable batch fields when calculating the existing canonical hash instead of deep-copying every observation. The numeric-domain validation still runs while reading, and SHA-256 still covers the same complete payload. The implementation also handles Windows JSON filename case consistently. Original code/binaries were retained separately.

The matched three-way comparison was:

| Implementation                | Median fresh-process report |         Range | Peak process working set |
| ----------------------------- | --------------------------: | ------------: | -----------------------: |
| Current Python reference      |                     6.381 s | 5.025–8.414 s |                 427.0 MB |
| First Rust version            |                     3.254 s | 2.817–5.420 s |                 712.2 MB |
| Borrowed-payload Rust version |                     2.628 s | 1.980–4.270 s |                 711.1 MB |

All used one warmup and seven interleaved measured fresh processes, and every full report matched the same Python oracle. The second version was **2.43x faster than Python**, or **58.8% less elapsed time by ratio of medians**. The median paired reduction was 55.9%, with a descriptive 95% paired-bootstrap interval of 51.4%–60.6% over 5,000 resamples. Those are different summary statistics and remain seven-sample local observations.

Within this same experiment, eliminating the copy reduced the Rust median from 3.254 to 2.628 s, about 19.2% less time. It barely reduced peak memory: generic parsed-object storage remained expensive. Under the plan's proposed default 20% memory-growth budget this prototype would not qualify for adoption without further work or a newly preregistered resource policy.

The Python baseline differed from the first experiment, which is why only within-run comparisons are used. The 2.43x figure is not calculated by comparing a native result against the earlier unrelated 4.614 s baseline. Both experiments verified unchanged production-source manifests from start to finish.

## Exact supported scope

This is a no-Python vertical slice of read-only reporting, not a full Rust AVO implementation. It supports the measured immutable per-request, source-reported usage profile, including mixed groups, unknown token totals, disjoint categories, exact decimal valuations, multiple valuation units, timestamps, Unicode, deduplication and conflicting observations.

Fourteen checks covered empty data, grouping, unknown counts, Unicode/control characters, explicit totals, disjoint categories, multiple valuation units, timezones, conflicts, all three existing large fixtures, rejection of changed batch bytes and rejection of an unsupported bindings path. Complete reports matched for supported cases; invalid integrity produced a failure rather than a partial report.

Prices, corrections, active bindings, cumulative/rollup usage, floating JSON values and wider numeric/decimal domains are explicitly unsupported by this prototype and fail closed. Its hand-written supported-profile checks do not replace every production JSON Schema or the existing 62-test accounting suite. Those gaps prevent production admission. There is no Python fallback hiding them.

The first optimized executable was 585,216 bytes and used Rust 1.95.0, locked serde_json 1.0.150, sha2 0.10.9 and chrono 0.4.44. This is the report program's size, not a forecast of full AVO's size. Python, FFmpeg, model weights and browser runtimes are not bundled into this prototype.

The borrowed-payload version was 590,336 bytes. Both binaries contain the reporting implementation rather than embedding or launching Python. Neither represents the complete AVO CLI, MCP server, editing engine, dependency toolchain or all accounting policy branches.

## What FULL Rust would mean for AVO

For a full AVO-owned runtime port, CLI, MCP, timeline rules, persistence, validation, reporting and adapters would run in Rust. External engines can retain their existing implementations: FFmpeg, CTranslate2, browser/motion runtimes and GPU libraries do not have to be rewritten to call the product a Rust application.

A completely Python-free toolchain is a broader requirement. It also needs replacements or ports for any Python-only transcription/alignment/review dependencies that remain in external processes. Calling a Python sidecar from a Rust executable removes Python from the caller, not from the entire workflow.

There is a plausible route to retaining the existing inference backend: the maintained [ct2rs 0.10.1 documentation](https://docs.rs/ct2rs/0.10.1/ct2rs/) exposes Rust bindings for CTranslate2, including Whisper and word-level timing structures. The [project build guide](https://github.com/jkawamoto/ctranslate2-rs/blob/main/README.md) documents native backend/CMake/GPU requirements. This establishes an integration option, not AVO transcription/alignment parity or a measured inference speedup. The [official Rust MCP SDK](https://github.com/modelcontextprotocol/rust-sdk) is another available integration path; AVO's exact protocol/gate behavior still needs qualification.

## How much would the whole workflow improve?

No full-product Rust timing exists. The report measurements above must not be called an 11.76x improvement to all of AVO.

For an unchanged serial workflow, if a fraction `f` of elapsed time becomes ten times faster and the rest remains unchanged, the calculated outcomes are:

| Replaceable elapsed fraction | Whole-workflow speedup | Total time saved |
| ---------------------------: | ---------------------: | ---------------: |
|                           5% |                 1.047x |             4.5% |
|                          20% |                 1.220x |            18.0% |
|                          50% |                 1.818x |            45.0% |
|                          80% |                 3.571x |            72.0% |

These are sensitivity calculations, not predictions. Overlapping work requires critical-path accounting. A two-times whole-workflow gain requires at least half of elapsed time to be replaceable even if that portion became instantaneous.

The earlier [encoded-proof experiment](runtime-migration-candidate-results.md) remains important: its diagnostic profile spent approximately 0.740 of 0.926 seconds in subprocess communication waits. Full Rust may reduce caller overhead, but keeping the same external engines/settings does not remove the time those engines consume. Replacing those engines or consolidating processes is a separately measured treatment.

## Full-port constraints that affect feasibility

- Canonical serialized bytes and hashes must remain compatible with existing revisions, locks and approvals. Ordinary serde_json output is not a general replacement for all CPython float/big-integer behavior. This prototype avoids that unproven domain.
- Exact source/sample/frame clocks and money calculations need preserved arithmetic and overflow behavior. A full Rust runtime cannot rely on a Python fallback for unsupported integers or decimals.
- Source admission, fresh verification, atomic publication, locking, recovery, cleanup preservation, CLI/MCP errors and human approval remain mandatory. Speed gained by omitting any of them is invalid.
- A native core can simplify the Python part of distribution, but models, GPU libraries, browsers, Node/HyperFrames and other external resources remain separate packaging questions. One report executable cannot certify a complete single-file toolchain.
- Keep the current modular-monolith and adapter boundaries. A language change alone does not justify new services, an abstraction framework or a new domain hierarchy.

The requested hybrid quality gate is still the first production implementation. A full Rust end state would use that gate during migration to compare the Python oracle with native slices, qualify supported targets and prevent partial ports from becoming the default before parity and performance pass.

## Decision supported now

Full Rust is a credible end-state option for faster startup and Python-heavy application work. This research now has a no-Python operation showing 11.76x faster small reporting and a separately matched optimized large-report case showing 2.43x, with a significant large-input memory regression. That is a stronger performance signal than the serializer-only hybrid tests, but it is not a measured whole-application comparison against those different harnesses.

For a migration decision focused on faster video completion, an end-to-end native slice still has to demonstrate useful improvement while retaining the same media/model output contracts. Full Rust does not imply 2.43x faster encoding or inference. For a decision focused on CLI latency, metadata/validation/report throughput and a native core distribution, the results support continued full-Rust feasibility work behind the requested gate. A final full-port recommendation remains conditional on connector parity, resource limits and representative workflow evidence.

## Evidence

- [First no-Python Rust report samples, memory and source identities](C:/Users/vitor/.codex/visualizations/2026/10/30/01a18ed7-d1f7-7c93-a58f-b22d832f3368/avo-runtime-research/full-rust-report/run-20261031T003015Z/results.json).
- [Matched Python/first-Rust/borrowed-Rust samples and uncertainty](C:/Users/vitor/.codex/visualizations/2026/10/30/01a18ed7-d1f7-7c93-a58f-b22d832f3368/avo-runtime-research/full-rust-report-borrowed/run-20261031T003703Z/results.json).
- [Isolated Rust source](C:/Users/vitor/.codex/visualizations/2026/10/30/01a18ed7-d1f7-7c93-a58f-b22d832f3368/avo-runtime-research/full-rust-report/src/main.rs).
- [Borrowed-payload Rust source](C:/Users/vitor/.codex/visualizations/2026/10/30/01a18ed7-d1f7-7c93-a58f-b22d832f3368/avo-runtime-research/full-rust-report-borrowed/src/main.rs).
- [Pinned build manifest](C:/Users/vitor/.codex/visualizations/2026/10/30/01a18ed7-d1f7-7c93-a58f-b22d832f3368/avo-runtime-research/full-rust-report/Cargo.lock).
- [Earlier hybrid candidate results](runtime-migration-candidate-results.md).

Raw timestamps use UTC and cross into 2026-10-31; the measurements occurred on 2026-10-30 in the user's America/Sao_Paulo timezone. Research source/build files remain external; no production implementation was migrated.
