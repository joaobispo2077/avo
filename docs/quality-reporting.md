# Quality reporting and evidence

AVO adapts quality measurements to its local CLI, MCP, and media-processing
risks. Existing lint, formatting, coverage, complexity, security, dead-code,
duplication, and import-boundary checks remain in place. Automated tests support
human architecture, safety, and editorial review.

## One report, one dashboard

The `Quality report` job waits for the mandatory jobs and `CI readiness`. It
combines the `quality-evidence` and `mutation-reports-light` artifacts from that
workflow run. One `quality-gates-report` PR comment and the job summary show the
overall result, full commit and run identity, required actions, one inline
dashboard, and a metric table. Each run updates the same PR comment in place.
The previous standalone mutation comment is removed.

The report separates **measurements**, **gate decisions**, and **execution
results**. The measurements table contains observed values, scope, input counts,
artifact links, and SHA-256 references. All nine fast gates plus mutation remain
visible in their own decision table with policy and captured execution evidence.
Required job results and JUnit testcase counts have a separate execution table.
Exception lists and contract definitions remain configuration diagnostics.

One image shows the three percentage measurements on separate scales. It does
not use PASS/FAIL labels or gate thresholds as measurement values. CRAP,
complexity, dependency findings, debt, and coupling use their own units in the
table and source-location diagnostics. Missing, skipped, cancelled, invalid, and
unfinished evidence stays unavailable or partial. Failed image generation or
artifact uploading leaves the text tables available.

`upload_quality_chart.py` uploads the PNG as a native GitHub image attachment
after verifying its embedded series against the normalized measurements and
current commit/run. A receipt records that identity, the image SHA-256, and the
returned attachment URL. The offline linker embeds the image only when the
receipt matches; the existing bot-owned sticky comment remains the publisher.
CI reporting keeps read-only repository contents permission and never creates
chart branches, Git objects, commits, or pushes.

The report job uses the existing `GH_TOKEN` secret from the `RELEASE`
environment, referenced with `deployment: false` to avoid deployment records.
`QUALITY_CHARTS_TOKEN` is only the uploader's private environment alias for that
credential; no new secret, token, or credential copy is required. Native uploads
support user credentials (OAuth, classic PAT, or fine-grained PAT) with
repository write access. The default installation `GITHUB_TOKEN` is unsupported
for attachments and remains responsible for the bot-owned comment; see the
[official CLI upload client](https://github.com/cli/cli/blob/v2.102.0/internal/attachments/client.go#L65).
Only trusted repository runs may use the upload credential. Fork PRs retain the
text and artifact-download fallback without receiving it. Missing credentials,
upload failures, and missing/stale image evidence cannot remove the measured
values or change gate decisions.

The raw PNG and normalized JSON also remain Actions artifacts linked from the
comment and job summary. Download links require GitHub sign-in and expire after
the current 14-day retention period; the text measurements and gate decisions
remain in the comment. Native attachments are separate from Actions artifacts
and do not inherit that expiry. Artifact URLs are accepted only for the same
repository and run.
The old `ci/quality-kpi-charts` branch is historical storage, not a source feature
to merge into `develop`. Existing branch history is left for the repository owner
to manage. Intentional release-cut snapshots retain their separate policy below.

Coverage reads its floor from `[tool.coverage.report]` in `pyproject.toml` in
both local and CI execution. Duplication uses `.jscpd.json`. The quality artifact
freezes the mutation profile and floor from `mutation-config.json`; the mutation
artifact must match that policy, commit, and run. The current floors remain
68% line coverage and 40%/50% light/full mutation, with a 2% duplication ceiling.
The artifact also freezes coverage.py's comparison precision. Coverage gate
decisions apply its rounding rule while the measurement retains the actual ratio.

Mutation efficacy is killed divided by killed plus survived, and is reported
only after validating complete, nonnegative integer outcome accounting. Timeout,
skipped, no-test, interrupted, crash, suspicious, or unaccounted outcomes make
the evidence incomplete. They are not kills or proven equivalent mutants.

## Artifact ownership and release compatibility

Gate jobs produce measurements. `write_unified_quality_report.py` combines their
evidence and required-job outcomes, then `quality_dashboard.py` supplies one
normalized series for both the text table and PNG. It never reruns gates.

`run_quality_gate.py` captures the exact command, exit outcome, timestamps,
stdout/stderr log, input source fingerprints, and produced-file hashes. It
returns the original command's failure. The publisher revalidates these captures
after downloading them; a matching job result alone cannot validate an input
file. Stale, changed, missing, and malformed captures cannot supply a zero result
or a successful measurement. Every artifact link comes from the upload action's
current-run URL, with the exact file and hash identified in the readout.

Schema 2 `quality-metrics` artifacts include commit, workflow run, mutation
policy, required-job results, counts, and the normalized dashboard series. The
release cut requires current-run green evidence; an older run or malformed
measurement cannot substitute for it. If a dashboard image is included, its
embedded series must exactly match the artifact. Historical schema 1 readouts
retain their decoding and chart validation, but cannot satisfy a request for a
current run-bound release. The versioned `measurement_evidence` extension records
normalized observations, capture proofs, and diagnostics. Older schema 2 records
remain readable and explicitly identify legacy summaries without raw capture.
PRs do not write `docs/quality-metrics.md`.

## CRAP, complexity, and coupling

`measure_code_risk.py` reuses installed Radon and coverage.py. Each function and
method has a module-qualified identity, source path, definition line, measured
cyclomatic complexity, and its own statement coverage. CRAP is:

`CC² × (1 − covered function statements / function statements)³ + CC`

The formula follows the [original CRAP proposal](https://www.artima.com/weblogs/viewpost.jsp?thread=210575).
AVO uses the function line-coverage variant, also supported by
[GMetrics](https://dx42.github.io/gmetrics/metrics/CrapMetric.html). Basis-path
coverage from the original proposal remains unmeasured. Radon supplies
[per-function cyclomatic complexity](https://radon.readthedocs.io/en/stable/api.html).

The inputs must share a successful coverage execution, SHA/run identity, raw
coverage hash, and unchanged source fingerprints. File or repository averages
never substitute for function coverage. Branch-instrumented profiles still use
the statement counts, not the combined line/branch percentage. Ambiguous,
unmatched, excluded, or zero-statement functions remain unmeasured. The maximum
is therefore labelled **max observed**, with measured and unmeasured function
counts. Source links, exact inputs, and the complete table live in `code-risk.json`.

Reference 30 is informational. This change does not add a CRAP gate or silently
adopt the manual's thresholds. Existing complexity gate limits and documented
exception ceilings still control enforcement.

The same report reuses the repaired static import graph for package CA (distinct
incoming packages), CE (distinct outgoing packages), and instability
`CE / (CA + CE)`. Instability is undefined for a package with no edges.
Aggregation is `avo.<package>`; intra-package and dynamic imports are not
measured. These counts identify review candidates, not proven god classes.
Abstractness, main-sequence distance, and quadrant cutoffs remain unmeasured.

## Coverage of the discussed catalog

| Concept | AVO treatment and evidence |
|---|---|
| Line coverage | Current unit-suite statement counts and percentage; `coverage.json`; unchanged 68% gate |
| Mutation | Current light profile counts with complete accounting; `mutation-metrics.json`; full profile remains a separately identified scheduled run |
| Duplication | Actual duplicated/total lines and clone pairs; `jscpd-report.json`; unchanged 2% gate |
| Cyclomatic complexity | Actual per-function scores and observed gate blocks; `code-risk.json` and `complexity.json` |
| CRAP | Informational per-function calculation from verified same-run inputs; explicit unmeasured functions |
| CA/CE coupling | Current static package graph, counts, and instability; `code-risk.json`; no speculative quadrant policy |
| Lint and formatting | Qualitative gate decisions and capture logs, not invented percentage metrics |
| Security | Actual Python/npm audits, advisory descriptions and fix versions, findings, policy, and command receipts |
| Dead code | Actual Vulture findings, unwaived count, matched exceptions, reasons and source lines; `deadcode.json` |
| Import boundaries | Executed kept/broken contract counts and capture log; configured contract count remains configuration |
| Dependency tree | Actual proposed add/remove/change counts from npm's dry run; `dependency-tree.json`; proposals are not applied or automatically blocking |
| Safety branches | Existing scheduled/manual safety measurement with its own commit/run identity; current PR line profiles explicitly do not measure branches |
| Unit and CLI/MCP/media integration | Actual JUnit testcase outcomes with raw XML and execution captures; no fabricated repair-success percentage |
| Fuzz/property smoke | Existing boundary and corrupt-input tests remain; no systematic fuzz-run metric or new testing dependency is claimed |
| Python type checking | Existing lint constraints remain; full Python type-check coverage is not measured |
| Browser/mobile E2E | AVO's CLI/MCP/media runtime coverage applies; blanket browser testing is not adopted |
| Trends | No historical trend infrastructure or manually entered KPI values are introduced |

The manual remains reference material. Its blanket 80% floors, mandatory test
ladder for every feature, and replacement of human review are not AVO policy.

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
own runtime calibration within the existing 20-minute budget. CRAP and CA/CE
are now measured informationally. Coupling quadrants, blanket 80% targets, trend
infrastructure, browser/mobile E2E for every feature, and new property-testing
dependencies remain outside this change.

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
initial local preview was verified at native and 390-pixel widths.
The [first published CI run](https://github.com/joaobispo2077/avo/actions/runs/38649097425)
passed all mandatory jobs on commit `e7eca7fc048edade8c8e55c297d5bf949bcb7aac`.
Its 71.42% coverage and complete 64.89% light mutation evidence belong to that
run. The follow-up capture, CRAP, and coupling changes require their own published
run; the historical measurements are not relabelled as fresh evidence.

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
- Initial local core line measurement: 71.32%, above the unchanged 68% floor.
  The broad local run had 17 reporting-fixture failures; those fixtures were
  corrected before the successful published run above, which measured 71.42%.
- Mapping mutation calibration: 175/178 killed (98.31%) with complete accounting;
  this is module-specific evidence, not the light/full CI profile's score.

### Measurement/evidence follow-up

The local `local-evidence-followup` run on 2026-10-14/15 used unchanged engine
sources from baseline commit `e7eca7fc048edade8c8e55c297d5bf949bcb7aac` and the
working-tree reporting changes. It is a local validation record, not a published
CI result for a new commit.

- Core execution: 1,875 tests and 103 subtests passed; 18,447/25,794 executable
  lines covered (71.52%). Runtime integration: 115 tests passed. Raw JUnit events
  independently confirmed the passing testcase counts with no failed/error/skipped
  events. The affected reporting/evidence cohort passed 279 tests and 34 subtests.
- All nine fast checks have validated current-run receipts. Complexity measured
  2,454 blocks with 178 matched exceptions and no unwaived/worsened/stale results.
  Vulture reported 150 findings with no unwaived findings. Duplication measured
  440/56,949 lines across 41 clone pairs (0.77%). Import-linter executed five kept
  and zero broken contracts; npm proposed 26 unapplied package changes.
- Verified function analysis observed 2,277 functions/methods, maximum CC 51.
  Exact coverage joins measured CRAP for 2,227 functions; 50 remain unmeasured.
  Maximum observed CRAP was 2,450, with 192 above informational reference 30.
  Static coupling measured 73 packages and 191 distinct internal edges, maximum
  CA 21 and CE 14. These are diagnostics, not newly adopted gate ceilings.
- The fresh Python audit found no unwaived advisories; npm reported zero critical,
  two high, seven moderate, and zero low findings under its existing policy.
- Native and 390-pixel preview checks found no clipped dashboard labels, page
  overflow, or color-only status. Narrow tables retain horizontal scrolling for
  their raw-evidence columns. Image metadata matches the normalized data exactly.

The local preview deliberately leaves mutation, safety branch coverage, and CI
job outcomes unavailable. The separate published/scheduled measurements retain
their own identities. The follow-up workflow still needs its own published CI
run after the scoped commits are approved and pushed.
