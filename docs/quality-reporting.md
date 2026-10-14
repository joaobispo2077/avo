# Quality reporting and evidence

AVO adapts quality measurements to its local CLI, MCP, and media-processing
risks. Existing lint, formatting, coverage, complexity, security, dead-code,
duplication, and import-boundary checks remain in place. Automated tests support
human architecture, safety, and editorial review.

## One report, one dashboard

The `Quality report` job waits for the mandatory jobs and `CI readiness`. It
combines the `quality-evidence` and `mutation-reports-light` artifacts from that
workflow run. One `quality-gates-report` PR comment and the job summary show the
overall result, full commit and run identity, required actions, one dashboard,
and a metric table. The previous standalone mutation comment is removed.

Coverage, duplication, and mutation have separate scales, explicit scope, raw
percentages, and threshold labels. Duplication is displayed directly. Gate
evidence, exceptions, contract counts, and downloadable artifacts live in
collapsed diagnostics; configuration counts are not quality scores. Missing,
skipped, cancelled, invalid, and unfinished evidence cannot yield a green
dashboard. Failed image generation or hosting leaves the text table available.

Coverage reads its floor from `[tool.coverage.report]` in `pyproject.toml` in
both local and CI execution. Duplication uses `.jscpd.json`. The quality artifact
freezes the mutation profile and floor from `mutation-config.json`; the mutation
artifact must match that policy, commit, and run. The current floors remain
68% line coverage and 40%/50% light/full mutation, with a 2% duplication ceiling.

Mutation efficacy is killed divided by killed plus survived, and is reported
only after validating complete, nonnegative integer outcome accounting. Timeout,
skipped, no-test, interrupted, crash, suspicious, or unaccounted outcomes make
the evidence incomplete. They are not kills or proven equivalent mutants.

## Artifact ownership and release compatibility

Gate jobs produce measurements. `write_unified_quality_report.py` combines their
evidence and required-job outcomes, then `quality_dashboard.py` supplies one
normalized series for both the text table and PNG. It never reruns gates.

Schema 2 `quality-metrics` artifacts include commit, workflow run, mutation
policy, required-job results, counts, and the normalized dashboard series. The
release cut requires current-run green evidence; an older run or malformed
measurement cannot substitute for it. If a dashboard image is included, its
embedded series must exactly match the artifact. Historical schema 1 readouts
retain their decoding and chart validation, but cannot satisfy a request for a
current run-bound release. PRs do not write `docs/quality-metrics.md`.

## Safety measurements and staged improvement

The scheduled/manual `mutation-full.yml` workflow also has an independent,
informational safety branch-coverage job. It instruments core unit tests,
excluding integration and private footage-project tests, and reports weighted
branch outcomes for canonical ancestry, approval decisions, timeline mapping,
cleanup preservation, and destructive request state. Missing files are
unmeasured, failed suites are incomplete, and uncovered branches include source
locations. The `branch-risk-reports` artifact retains its raw JSON and readout
for 14 days, with commit/run/UTC provenance. This does not replace the PR line
coverage gate or introduce a branch-coverage floor.

Use these measured gaps to select meaningful tests and small behavior-preserving
debt reductions. The full mutation profile now includes pure timeline mapping,
selected through a complete timed Linux calibration with the locked tooling;
the light profile is unchanged. Its tests cover exact timebase conversion,
boundaries, and accumulated offsets. Additional mutation batches require their
own runtime calibration within the existing 20-minute budget. CRAP, coupling quadrants, blanket 80%
targets, trend infrastructure, browser/mobile E2E for every feature, and new
property-testing dependencies are outside this change.

The mapping-only calibration on 2026-10-14 used locked mutmut 3.7.0, pytest
9.1.1, and pytest-cov 7.1.0 in an isolated Linux environment: 175 killed and
3 survived out of 178 complete mutants, with no unresolved outcomes. Mutation
execution took 46.87 seconds. This measures the selected module, not the full
scheduled job. Four additional boundary/timebase cases killed eight behavioral
survivors; two diagnostic-string changes and an arithmetic-initializer candidate
remain visible, without blacklisting or exclusions. The engine source was
unchanged (`51112f69ba8fee925203ed2ff420b77b716f4cc29aee1e656c7161919376aafc`).

The optional dependency diagnostic now resolves internal absolute and relative
imports and multiple aliases, preserves isolated packages, and exposes a
self-contained HTML dependency table plus DOT export. It binds results to the
checkout SHA and UTC generation time and remains outside the PR fast path.

## GitHub enforcement

`CI readiness` runs even when dependencies fail and requires successful Gate 1,
unit tests, integration tests, Software quality, Gate 2, and light mutation.
PR targets include `develop`, `release`, and `main`. Supported MCP integration
tests require the MCP extra in CI instead of silently skipping.

The dependency audit installs the same frozen MCP extra locally and in CI.
Every unwaived Python advisory still blocks; npm retains its existing critical
severity policy. This includes runtime dependencies that a dev-only install
would otherwise omit.

The first audit with MCP installed exposed 17 advisories in the existing lock.
A focused refresh updates HTTPX2/HTTPCore2 from 2.10.0 to 2.12.0 and PyJWT from
2.13.0 to 2.15.0, retaining MCP 2.0.0 and other dependency versions. The resolver
also reconciles the root lock entry with the already declared AVO version.

Live inspection on 2026-10-14 found only a deletion/non-fast-forward ruleset on
`main`; `develop` and `release` were unprotected. After these workflow changes
are published and their check names registered, enable the documented required
checks, including `CI readiness`, on all three branches. No live ruleset or
branch changes are made by this implementation.

The rendered [quality comment on PR #89](https://github.com/joaobispo2077/avo/pull/89#issuecomment-6102461795)
was also inspected. Its seven images were unavailable after a non-fast-forward
hosting failure, leaving repeated tables and the inverted duplication score.
The replacement keeps one metric table usable when image hosting fails. Its
local preview is verified at native and 390-pixel widths; its first published
GitHub run remains a rollout check.

## Validation evidence

- Final reporting, readiness, mutation accounting, dependency diagnostics,
  acceptance evidence, and mapping cohort: 159 tests and 62 subtests passed.
  Scenarios include success, failure, skipped/missing evidence, timeouts,
  stale commits/runs, and inconsistent mutation counts.
- Runtime integration cohort: 151 tests passed with MCP installed; after the
  focused dependency update, 54 MCP/runtime/approval regressions passed.
- Lint, formatting, complexity, dead-code, duplication, import boundaries,
  dependency tree, and dependency security checks passed. The MCP-inclusive audit
  found no unwaived Python advisories and no npm criticals; two npm high and seven
  moderate findings remain reported under the existing policy.
- Core line measurement: 71.32%, above the unchanged 68% floor. The broad core
  run had 17 reporting-fixture failures; those fixtures were corrected and their
  affected suites passed in the final cohort above. A full final-tree repeat
  remains for published CI; this is not a claim that one final full run was green.
- Mapping mutation calibration: 175/178 killed (98.31%) with complete accounting;
  this is module-specific evidence, not the light/full CI profile's score.
