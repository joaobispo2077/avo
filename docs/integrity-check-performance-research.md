# Integrity-check performance research

Measured 2026-10-31. Research only: no AVO product code, dependency declaration, default runtime or quality-gate implementation was changed. Prototypes and generated inputs remain outside the repository.

The strongest result for the current pre-render preflight was **821 ms to 229 ms, 3.59x faster and 72.1% less time**, using Python experiments that share schema setup within a checked batch and hash independent source files concurrently. A separate experiment replacing only source hashing with Rust reduced the same kind of preflight by **9.7%**. This supports reducing repeated work before deciding whether this responsibility needs a language migration.

These are controlled experiments on the current `ProofPlanCompiler.preflight`, not an implemented AVO improvement or an observed speedup for the user's complete video. The synthetic fixture uses five canonical artifact heads, one graph operation and four distinct 64 MiB source files, totaling 256 MiB. These are hash inputs, not representative encoded camera media; this preflight checks their bytes without decoding them.

## Where current preflight time goes

`src/avo/timeline/proof_plan.py` checks plan identity, canonical revisions, source fingerprints, lineage declarations, output aliases, implementation identity, capability resolution and tool readiness, then creates a deterministic report. Its source-lock loop hashes files sequentially. Canonical artifact reads repeatedly invoke document validation.

`src/avo/timeline/contracts.py` rebuilds the local schema registry for each `validate_document` call. A separate diagnostic profile recorded:

| Responsibility | Instrumented time | Observation |
| --- | ---: | --- |
| Complete preflight | 867 ms | Profiling adds overhead. |
| Canonical preflight | 524 ms | Includes validation below. |
| Document validation | 513 ms | 25 invocations. |
| Schema registry construction | 439 ms | 25 builds scanning about 50 schema files each. |
| Source fingerprints | 297 ms | Four fresh 64 MiB file hashes. |
| Implementation registry | 41 ms | Includes implementation-source reads/hashes. |

These times are nested and must not be added. About 1,250 schema-registry document reads and 1,300 total JSON text loads were recorded. Repeated setup and file operations are substantial costs in this fixture.

## Actual preflight experiments

Each table has its own interleaved baseline. Do not mix baselines across runs.

First experiment, changing only the file-fingerprint responsibility:

| Variant | Median | Less time than baseline |
| --- | ---: | ---: |
| Current AVO | 824.560 ms | Baseline |
| Python reusable read buffer | 780.177 ms | 5.4% |
| Rust in-process file hashing | 744.232 ms | 9.7% |
| Four Python hashing threads | 620.837 ms | 24.7% |

Second experiment, sharing schema setup while retaining every existing document validation:

| Variant | Median | Less time | Speedup |
| --- | ---: | ---: | ---: |
| Current AVO | 820.683 ms | Baseline | 1x |
| One checked schema registry per batch | 429.588 ms | 47.7% | 1.91x |
| Same reuse plus four Python hashing threads | 228.872 ms | 72.1% | 3.59x |

Registry reuse includes a fresh SHA-256 inventory of every schema JSON file before the first build and again before returning. Changed bytes or membership reject the operation. Document validation, canonical revisions, exact file hashes, implementation checks and report generation remain inside timing. The parallel variant computes all four fresh fingerprints inside the timer before current preflight consumes them.

Both experiments used two warmups and 15 measured rounds per variant, rotated interleaved, with warm filesystem caches on Windows/i7-11800H/Python 3.11.3. These are preliminary bounded samples, not stable p95 estimates. Descriptive paired-bootstrap 95% reduction intervals were 7.6%–11.5% for Rust hashing, 23.1%–27.0% for Python parallel hashing, 46.0%–48.5% for registry reuse and 71.5%–72.6% for combined reuse/concurrency. These finite-sample intervals are not cross-machine guarantees.

Complete timed reports matched baseline. Additional comparisons retained changed-plan, changed-source and missing-source blocker reports. Schema mutation was rejected by the experimental byte guard. This is not full schema, concurrency or admission qualification. Fixture publication used exclusive copies because the host denied hardlinks; setup/compilation were outside timing, and measured preflight was read-only.

The boundary excludes fresh CLI startup, plan compilation/loading validation, FFprobe stream checks, decode/render work, microproof evaluation and closing render rechecks. The actual user invocation, video sizes/counts and storage still need their own trace.

## Hashing alone

A separate five-warmup/30-round comparison required identical SHA-256, observed byte count and locator for the same 256 MiB file:

| Variant | Median | Less time than current AVO |
| --- | ---: | ---: |
| Current AVO fingerprint | 302.260 ms | Baseline |
| Python `hashlib.file_digest` primitive | 220.313 ms | 27.1% |
| Python reusable 1 MiB buffer | 224.014 ms | 25.9% |
| Rust in-process 1 MiB buffer | 215.478 ms | 28.7% |
| Fresh Rust worker, invocation included | 231.492 ms | 23.4% |

Rust was only 1.04x the reusable-buffer Python control by medians. Much of the gain is reproducible through read/allocation strategy with Python orchestration. This is not a language-only comparison: the paths use different SHA-256 implementations and boundaries.

The Rust prototype uses pinned `sha2` 0.10.9 in an offline optimized Rust 1.95.0 build. It does not implement AVO's cache, mutation-stage contract or complete preflight in Rust. Forty-eight small-file comparisons covered empty files, Unicode paths and block/chunk boundaries across four methods; a missing native input was also rejected.

A separate two-warmup/15-round batch used four distinct 64 MiB files and current AVO fingerprinting: sequential **288.432 ms**, two Python threads **151.746 ms** (1.90x), four threads **82.593 ms** (3.49x). This ran outside production stage/cache context. Cold files, a large single file, external drives and busy storage remain unmeasured.

Python can hash concurrently because `hashlib` releases the GIL for sufficiently large updates; AVO uses 1 MiB updates. [Python 3.11 hashlib documentation](https://docs.python.org/3.11/library/hashlib.html).

## Verification boundaries remain necessary

The current `proof_validation_batch` already reuses fingerprints within its scope. Three requests for one unchanged 256 MiB file produced two actual reads, totaling 512 MiB: the first observation and the closing fresh hash. A file changed during the batch was rejected. The final pass checks a different point in time; it is not an unnecessary duplicate.

The executor also checks actual streams through FFprobe, validates graphs/generated inputs, renders through FFmpeg and checks outputs. Full proof preflight and execution use separate scopes. Their total cost was not measured here. Sharing observations or admitting threads must preserve parent observations, failures and closing fresh verification. Nothing here justifies substituting file metadata for a hash or removing the closing pass.

## Migration implication

Rust can implement faster loops, scheduling and schema processing. The largest measured preflight gain here, however, came from Python experiments retaining current validators. A full Rust preflight could accelerate other responsibilities too; it has not been built or benchmarked, and the 9.7% hashing-only result is not its maximum possible gain.

For other integrity checks, [earlier research](runtime-migration-candidate-results.md) measured up to 7.7x faster supported-profile canonical JSON serialization. That is not a complete check speedup and excludes subsequent SHA-256. Media decoding, FFprobe, FFmpeg, inference and repository test/tool runs have separate costs. There is no universal integrity-check multiplier.

The next performance candidates are verified schema-registry reuse, bounded concurrent hashing and reusable-buffer/native hashing under a common contract. The planned hybrid quality gate remains the first requested production implementation. No candidate has been installed into AVO.

## Evidence

Source manifests were unchanged from the start to the end of each timed experiment. Samples, native artifact/source hashes, scripts and reports are external:

- [File hashing and thread batch](C:/Users/vitor/.codex/visualizations/2026/10/30/01a18ed7-d1f7-7c93-a58f-b22d832f3368/avo-runtime-research/integrity-hash/run-20261031T155153Z/results.json).
- [Current preflight with hash candidates](C:/Users/vitor/.codex/visualizations/2026/10/30/01a18ed7-d1f7-7c93-a58f-b22d832f3368/avo-runtime-research/integrity-hash/preflight-20261031T155528Z/results.json).
- [Preflight profile](C:/Users/vitor/.codex/visualizations/2026/10/30/01a18ed7-d1f7-7c93-a58f-b22d832f3368/avo-runtime-research/integrity-hash/preflight-20261031T155528Z/profile.txt).
- [Current preflight with guarded registry reuse](C:/Users/vitor/.codex/visualizations/2026/10/30/01a18ed7-d1f7-7c93-a58f-b22d832f3368/avo-runtime-research/integrity-hash/schema-batch-20261031T155804Z/results.json).
- [Native build and artifact identities](C:/Users/vitor/.codex/visualizations/2026/10/30/01a18ed7-d1f7-7c93-a58f-b22d832f3368/avo-runtime-research/integrity-hash/build.json).

This report adds research documentation only. It does not claim full repository quality validation, packaging or cross-platform qualification, production mutation/concurrency parity or a measured complete-video speedup.
