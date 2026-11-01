# AVO native migration experiments: measured gains

Follow-up: [full-Rust feasibility and no-Python report measurements](full-rust-feasibility.md) now test a standalone native operation, including startup, integrity/accounting work and memory. Those results are separate from the hybrid implementations below.

Date: 2026-10-30. Scope: isolated research authorized before a migration decision. No product operation, dependency declaration, default runtime, branch, or production quality gate was changed by this research.

The measured result supports selective acceleration, with substantial variation by workload. It does not establish a performance case for rewriting all of AVO. The strongest practical result here is a **12.3% faster fresh CLI cost report at 100,000 observations**, saving about **0.51 seconds**. A small report became slower. A representative encoded proof did not demonstrate a material improvement.

## Comparisons that exercise current AVO operations

Each row compares its own baseline and candidate in the same interleaved experiment. Do not combine an earlier baseline from another run with a later candidate: workstation frequency/cache conditions changed enough to make those comparisons misleading.

The Rust path uses orjson 3.13.0 plus a Rust compatibility guard. The C path uses msgspec 0.22.0 plus a C compatibility guard. Both retain Python orchestration and the original serializer/decoder for unsupported values. These are package/integration comparisons, not a controlled proof that one language is universally faster. orjson also uses native C code internally.

| Complete measured operation                                 | Current Python | Rust package path | C package path | Point result                                                                    |
| ----------------------------------------------------------- | -------------: | ----------------: | -------------: | ------------------------------------------------------------------------------- |
| Canonical serialization, 10,000 items                       |       8.388 ms |          1.068 ms |       1.366 ms | Rust 7.86x; C 6.14x                                                             |
| Canonical serialization, 100,000 items                      |      86.134 ms |         11.232 ms |      18.608 ms | Rust 7.67x; C 4.63x                                                             |
| Warm cost report, 10,000 observations                       |     293.779 ms |        229.243 ms |     206.488 ms | Rust 22.0% less time; C 29.7%                                                   |
| Warm cost report, 100,000 observations                      |        3.709 s |           3.155 s |        2.914 s | Rust 14.9% less time; C 21.4%                                                   |
| Fresh CLI cost report, 100,000 observations                 |        4.131 s |           3.728 s |        3.621 s | Rust 9.7% less time; C 12.3%                                                    |
| Fresh CLI cost report, 1,000 observations                   |     716.375 ms |        848.293 ms |     763.264 ms | Rust 18.4% longer; C 6.5% longer                                                |
| Current encoded proof executor, source-fingerprinted replay |     929.402 ms |        968.132 ms |     908.617 ms | Rust 4.2% longer; C 2.2% less time; neither demonstrates a large rendering gain |

Canonical serialization means producing exact canonical bytes; it excludes the subsequent SHA-256. The cost-report rows include actual store reads, integrity/hash checks, observation resolution, accounting, aggregation and breakdowns. CLI rows additionally include a fresh Python process, imports, parser, project context, report generation and structured output. No price math, validation, fingerprints or output requirements were removed.

The candidate CLI harness currently loads both package/guard sets; the baseline loads neither. The measured startup penalty includes that conservative research-loader cost. A production loader could load only its selected path, but that improvement is not measured or subtracted here.

Short operations and the 10k report used five warmups and 30 measured samples per variant. Expensive 100k reports, fresh-process CLI and encoded-proof cases used one warmup and seven measured samples under an explicit bounded-run exception. All results and slow samples are retained; no stable p95 is claimed from seven samples.

## Uncertainty, memory and practical magnitude

Headline percentages are ratios of medians. The intervals below are descriptive 95% paired-bootstrap intervals for the median paired reduction, using 5,000 resamples and a fixed seed. They describe these finite workstation samples, not other machines or a release qualification.

| Comparison                         | Paired reduction interval | Interpretation                                                                    |
| ---------------------------------- | ------------------------: | --------------------------------------------------------------------------------- |
| 100k canonical serialization, Rust |             86.83%–87.17% | Strong local component improvement.                                               |
| 100k canonical serialization, C    |             78.13%–79.05% | Strong local component improvement.                                               |
| Warm 100k report, Rust             |             10.58%–25.98% | Improvement observed; magnitude still uncertain.                                  |
| Warm 100k report, C                |             16.83%–32.29% | Improvement observed; seven samples remain preliminary.                           |
| Fresh 100k CLI, Rust               |              8.22%–16.18% | Smaller gain after startup/import costs.                                          |
| Fresh 100k CLI, C                  |             10.99%–17.85% | About half a second saved per tested invocation.                                  |
| Fresh 1k CLI, Rust                 |         -35.11% to -5.36% | Startup penalty outweighs saved work.                                             |
| Fresh 1k CLI, C                    |         -19.14% to -1.87% | No gain for this tested small invocation.                                         |
| Encoded proof replay, Rust         |          -4.17% to 17.04% | Direction/size uncertain; no material benefit established.                        |
| Encoded proof replay, C            |              1.44%–11.50% | Small local point improvement; insufficient evidence for a broad rendering claim. |

At 100k observations the median peak process working set was approximately 410 MiB for baseline, 443 MiB for the Rust path and 424 MiB for the C path. The actual byte counters are retained. This is process peak working set on Windows, not a process-tree/GPU/energy measurement. The CLI has no inference or rendering child in this experiment.

Illustrative scale only: 100 of the tested large C-path CLI reports would save about 51 seconds. If a ten-minute workflow contains one such report and nothing else changes, 0.51 seconds is approximately 0.085% of its total. Neither the invocation frequency nor the ten-minute workflow is an observation of the user's videos.

## A failed integration is part of the evidence

The first serializer experiment retained a recursive compatibility check in Python. Native encoding became faster internally, but complete 100k reports became **26.6% longer with the Rust package** and **19.5% longer with the C package**. At 10k observations the penalties were 32.3% and 20.9%.

Moving compatibility traversal into native code produced the positive results above. This demonstrates why conversion, domain checks, fallback and complete operation timing must be measured together. Installing a fast library alone did not produce the improvement.

Unsupported floats, large integers, tuples/subclasses, non-string keys and other values use the original path. This preserves the tested original bytes or rejection behavior instead of silently normalizing nonfinite values, changing canonical hashes or clamping integers. The guard is research code tied to the CPython 3.11 release ABI. Concurrent mutation between eligibility checking and encoding, broader numerical domains, ABI portability and production hardening still require the hybrid gate; these fixtures do not prove universal equivalence.

## Rust, Go and C on the same bounded mapping responsibility

Separate prototypes implement the same homogeneous-clock integer scan, retaining Python fallback for other clock/domain inputs. Preparation, bounds/domain checking, array/wire conversion, invocation and result conversion are included. The current function repeatedly uses exact `Fraction` operations; a Python integer fast path is the algorithm control.

| 2,000 segments and 128 lookups    |       Median | Relative to current Python |
| --------------------------------- | -----------: | -------------------------: |
| Current `cmap_output_to_raw` loop | 1,259.690 ms |                         1x |
| Python integer fast path          |    57.130 ms |                     22.05x |
| Rust in-process library           |     3.585 ms |                    351.38x |
| C in-process library              |     3.530 ms |                    356.90x |
| Rust fresh worker                 |    25.749 ms |                     48.92x |
| C fresh worker                    |    23.717 ms |                     53.11x |
| Go fresh worker                   |    30.772 ms |                     40.94x |

The native in-process paths were about 16x faster than the optimized Python control on this large batch. This includes conversion; it is not merely a kernel timer. C and Rust's close medians do not establish a general language winner. Go was tested as a worker, not a cgo extension, so compare it with the other workers when assessing language/runtime shape.

At 32 segments and 128 lookups, current Python took 18.793 ms, the Python control 0.785 ms, Rust/C libraries 0.180/0.143 ms, and fresh workers 23.7–28.5 ms. At 16 segments and one lookup, current Python took 0.168 ms while workers took 31.7–43.5 ms. Worker startup can erase a native computation gain.

These functions have **no direct internal callers found in the inspected source** beyond their definitions. Their standalone improvement is therefore not evidence that an existing video pipeline becomes hundreds of times faster. It demonstrates the size of a possible batch benefit if an actual caller/profile justifies this responsibility. It is not the recommended first production port on its own.

All mapping variants used five warmups and 30 measured samples per workload. Differential checks covered 65 fixture cases and 390 method comparisons, including exact endpoints, negative/out-of-range queries, zero-duration segments, large-number fallback, empty maps and mixed timebases. Further adversarial and concurrency coverage is still needed for adoption.

## Why the video result is modest

The proof experiment used actual `execute_ffmpeg_proof`: two freshly generated original sources, source/graph checks, a 60-frame 640×360 output at 30000/1001, stereo 48 kHz AAC, FFmpeg encoding, FFprobe observations and output fingerprints. Candidate and baseline outputs were byte-identical, with frame/routing/signal assertions. Source generation was outside timing. It is a synthetic technical proof, without Watch/inference, human editorial approval or a complete long-form delivery.

A separate diagnostic profile took 0.926 s; approximately 0.740 s was in subprocess communication lock waits. Process creation took about 0.052 s, file opens 0.059 s and reads 0.016 s. Two registry constructions performed implementation-source digest work totaling about 0.087 s. Nested times must not be summed. Parent process CPU was 0.188 s and excludes child CPU; profiling overhead is included.

This points toward work-count, process and I/O investigations as well as language choices. It does not authorize caching away required final verification. Accelerating JSON alone cannot remove encoding/probing waits. A full rewrite might change those boundaries, but that is an additional design/backend experiment whose gains have not been measured here.

## Distribution and readiness observations

Research builds used Rust 1.95.0, MSVC 14.35 tools with `/O2 /W4 /WX /std:c17`, and official portable Go 1.27.3 with `CGO_ENABLED=0`. The Go archive was checked against the official SHA-256. All tools, wheels, source prototypes and native artifacts remain in the external research folder; AVO's dependency declarations and environment were not changed.

Mapping worker sizes were C 118,784 bytes, Rust 2,114,362 bytes and Go 2,272,256 bytes with the recorded default optimized linking settings. Those are tiny research programs, not full AVO distributions. C's CRT and the hybrids' Python/native dependencies still matter. No full engine size, clean-machine installation time, signing result, macOS/Linux/WSL speed or Python-free AVO capability is inferred from them.

The following checks were actually completed:

- Exact canonical/rejection/read-fallback corpus: 1,060 comparisons under each native guard, all equal.
- Existing accounting suites `test_costs`, `test_cost_invariants`, `test_cost_contracts`, `test_cost_closure`, and `test_cost_responses`: **62 passed for each candidate** in isolated processes.
- Mapping: 390 differential comparisons and 840 measured operation samples.
- Encoded-proof comparisons: identical output bytes and frame/audio checks, with the repeated run's source closure unchanged from start to finish.

This is not full `npm run quality`, native sanitizer/coverage/mutation qualification, packaged release certification or the implemented hybrid quality gate. No production candidate is admitted by these measurements.

## Decision supported by the numbers

Keep the current orchestrator while establishing the requested hybrid quality gate. The measured candidates justify evaluating selective JSON/report acceleration for large workloads, with native compatibility checks and explicit fallback. Rust won the canonical-serialization component test; the C package path won the tested complete accounting/report cases. Neither establishes a full-language migration winner. The Go worker is viable for coarse batches but loses badly on small calls.

For a performance-only decision today, a whole-AVO rewrite has no demonstrated gain large enough to justify it. The available measured gains are workload-specific: up to 7.7x canonical serialization, roughly 15%–30% less warm reporting time depending on candidate/scale, about 10%–12% less time for the large fresh CLI report, regressions on the small fresh CLI, and no material broad rendering improvement established. A source-code ratio such as 20/80 does not predict an overall speedup.

## Evidence and reproducibility

All experiments were run sequentially on the same Windows i7-11800H/16-logical-CPU workstation with Python 3.11.3 and warm files. Correctness/instrumented tests were separate from uninstrumented timing. Full samples, rejected approaches, scripts, source hashes, native artifact hashes, build commands, output identities and bootstrap parameters are retained:

- [Comparative summary and evidence identities](C:/Users/vitor/.codex/visualizations/2026/10/30/01a18ed7-d1f7-7c93-a58f-b22d832f3368/avo-runtime-research/candidates/comparative-summary.json).
- [Mapping samples](C:/Users/vitor/.codex/visualizations/2026/10/30/01a18ed7-d1f7-7c93-a58f-b22d832f3368/avo-runtime-research/candidates/mapping-results-20261030T230553Z.json).
- [Initial Python-guard regressions](C:/Users/vitor/.codex/visualizations/2026/10/30/01a18ed7-d1f7-7c93-a58f-b22d832f3368/avo-runtime-research/candidates/json-results-20261030T230750Z.json).
- [Native-guard samples and source/artifact identities](C:/Users/vitor/.codex/visualizations/2026/10/30/01a18ed7-d1f7-7c93-a58f-b22d832f3368/avo-runtime-research/candidates/native-guard-results-20261030T231315Z.json).
- [Large fresh CLI samples and memory](C:/Users/vitor/.codex/visualizations/2026/10/30/01a18ed7-d1f7-7c93-a58f-b22d832f3368/avo-runtime-research/candidates/cli-100000-20261030T231631Z/results.json).
- [Small fresh CLI samples and memory](C:/Users/vitor/.codex/visualizations/2026/10/30/01a18ed7-d1f7-7c93-a58f-b22d832f3368/avo-runtime-research/candidates/cli-1000-20261030T231840Z/results.json).
- [Source-fingerprinted proof replay](C:/Users/vitor/.codex/visualizations/2026/10/30/01a18ed7-d1f7-7c93-a58f-b22d832f3368/avo-runtime-research/candidates/proof-20261030T232706Z/results.json).
- [Proof diagnostic profile](C:/Users/vitor/.codex/visualizations/2026/10/30/01a18ed7-d1f7-7c93-a58f-b22d832f3368/avo-runtime-research/candidates/proof-profile-20261030T232508Z/profile.txt).

A concurrent working-tree edit added MP4 movie timescale handling in `proof_executor.py` at 23:16:09 UTC, before proof timing. Accounting/mapping code did not change. Proof results use the later source identity, and the replay verifies unchanged start/end source manifests; earlier accounting baselines retain their own manifests. The research did not apply that edit or revert it.

Primary project documentation for the mechanisms: [orjson](https://github.com/ijl/orjson), [msgspec](https://github.com/msgspec/msgspec), [Go downloads and official checksums](https://go.dev/dl/?mode=json), and [CPython extension API](https://docs.python.org/3.11/extending/extending.html). These sources support ecosystem/compatibility facts; performance numbers in this report come from the retained local experiments.
