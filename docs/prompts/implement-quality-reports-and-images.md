# Prompt 2: Implement evidence-based quality reports and images

Copy the prompt below into an AI agent working in the target repository after the quality commands and evidence contract exist. It is self-contained and does not require the conversation that produced Prompt 1.

---

You are working in the current project. Implement a separate reporting layer for the project's existing quality gates and KPIs. It must produce accurate human-readable reports, machine-readable normalized readouts, and actual rendered report images from recorded execution evidence.

Complete implementation and validation. Do not stop at recommendations, chart mockups, a proposed dashboard, or a tool list. Choose the implementation from this project's structure, existing tools, publishing capabilities, and conventions. No language, charting library, framework, serialization format, CI provider, image host, reporting platform, or commercial product is prescribed.

## 1. Respect the producer/consumer boundary

Quality commands own analysis, test execution, measurements, policy enforcement, and evidence capture. This reporting task owns evidence validation, normalization for presentation, report composition, image rendering, and appropriate delivery.

The reporter must accept saved evidence and work without rerunning lint, tests, coverage, mutation, security scans, or other quality checks. It must be usable after artifacts have been downloaded or while the producer toolchain is unavailable. Do not make the ordinary quality command depend on the reporter.

Do not change gate thresholds, source/test scope, exceptions, command exit semantics, required-check behavior, or metric definitions to make reports look better. Do not create a new gate merely by coloring a chart or adding a reference line.

If the existing evidence cannot support a metric, show that metric as unavailable with the exact reason and identify the missing producer capability. Do not scrape an old report, infer a measurement from a successful job, manufacture example data as a real run, or silently run a missing check. Document a minimal producer-contract improvement separately if necessary.

Preserve existing product behavior, unrelated changes, branch policy, compatible report consumers, and approved visual conventions. Reuse the project's tools and design before adding dependencies. Do not build a reporting website, database, external service, credentials, or a generic plugin system unless required by the current project's actual delivery needs.

## 2. Inspect the current project and reporting contract

Read applicable instructions, architecture, quality documentation, commands, configuration, and CI workflows. Trace the active report entry point and callers; do not assume an older retained renderer or screenshot is the current design.

Inspect at least one actual saved execution, representative failing/incomplete evidence, and independent fixtures where available. Establish:

- Project/components and the audiences/decisions the report supports.
- Existing check IDs, metric IDs, definitions, units, scopes, aggregation grains, semantic versions, and evidence schemas.
- Gate policy, authoritative configuration, and the frozen policy carried with each run.
- Distinctions between observed values, gate decisions, job/command outcomes, and configuration/debt diagnostics.
- Artifact paths, capture manifests, hashes, source fingerprints, and source-location references.
- Local versus CI identity, tested revision versus change-request head/base, retry attempts, and scheduled/full versus fast profiles.
- Existing primary/supporting charts, approved styling, text reports, summaries, comments, release snapshots, publication ownership, and retention.
- How reports are consumed on desktop and narrow/mobile screens and whether report artifacts must work offline.
- Existing permissions, trust boundaries, and supported delivery/attachment mechanisms. Read credentials only through approved mechanisms and never print their values.

Create a report/view matrix before editing. For each metric/view, specify its evidence source, valid population, unit, formula, state handling, visual encoding, scope label, references/thresholds, ordering, truncation/index behavior, and output artifacts. State what will remain unavailable and why. Briefly explain the design, then implement it.

## 3. Establish one validated semantic model

Use one normalized model as the input to every table, image, downloadable readout, and publication output. Avoid independent calculations in the chart and text renderer.

For each measurement, retain:

- Stable ID, semantic revision, name, classification, and unit.
- Exact scope/grain and profile, input population and exclusions.
- Raw counts/inputs and unrounded numeric value when valid.
- Measurement state and completeness, with reasons and measured/unmeasured/unknown counts.
- Frozen comparator, threshold, authoritative precision/rounding, recorded gate decision, and enforcement mode where applicable.
- Evidence/source references, content hashes, source identity, and producing execution.
- Visual interpretation fields derived by explicit documented rules, without overwriting the raw measurement or gate result.

Keep these report sections separate:

1. **Measurements:** actual values and evidence.
2. **Gate decisions:** categorical policy decisions, including accepted debt and non-blocking findings.
3. **Execution results:** command/job outcomes and observed test execution events.
4. **Configuration diagnostics:** exceptions, configured contracts, exclusions, or unapplied proposals.

Do not create an overall quality percentage, average unrelated KPIs, convert gate statuses into percentages, or present passing-check counts as measured code quality. Counts may summarize categories only when their populations and meaning remain explicit.

## 4. Validate evidence before presenting values

Validate schema/version, required fields, count domains, identity, policy/profile, scope, content hashes, and references before using artifacts. Keep artifact reads within the allowed evidence root. Treat artifact contents, source names, logs, XML, and URLs as untrusted data; escape rendered text and do not execute commands embedded in evidence.

Reject or visibly quarantine inconsistent revision/run/attempt/profile inputs. Do not silently choose whichever file has the newest modification time. Source references and graph/function joins must match the measured source fingerprints.

Use explicit availability/completeness states. Retain the native reason and map outcomes consistently:

- Valid measured zero is different from missing data.
- Missing, invalid, partial, unsupported, not applicable, not run, skipped, canceled, and timed out are different conditions.
- A recorded passing gate without valid required execution proof is visibly incomplete/unverified; retain the original recorded claim separately if useful.
- A failed gate with a valid measurement still has a real measured value. Do not hide failing observations.
- A partial scan/test run may have valid observed events, but do not present it as a complete population or complete certification.
- A failed image renderer is a presentation failure; it does not change the underlying gate or measurement.

Do not coerce missing/invalid values into zero, show a missing score as 100%, or call an unexecuted required check successful. Do not replace missing current evidence with a previous successful run.

## 5. Preserve metric meaning exactly

Only display metrics supported by the project's evidence. Apply these rules where the metrics exist:

### Coverage

- Name the measured kind: line/statement, branch, function, or another instrumented kind.
- For line/statement coverage, use matching raw counts and `100 * covered / executable` with a positive denominator.
- Preserve scope, exclusions, raw counts, precision, and execution completeness.
- Never infer branch coverage from line coverage. Never relabel file/repository averages as a function's coverage.

### Duplication

- Use the actual duplicated-unit percentage, including the tool's documented overlap/counting rules.
- For duplicated-line coverage, use `100 * duplicated_lines / total_lines` and retain clone locations where available.
- Label it lower-is-better. Do not plot `100 - duplication`, call it a similarity-free quality score, replace the value with its ceiling, or reverse its legend.
- Validate contradictory counts/percentages against a documented tolerance; inconsistent data remains unavailable.

### Mutation

- Use the producer's explicitly defined convention and label the active source/profile/operator scope.
- Under a complete-verdict convention such as AVO's, efficacy is `100 * killed / (killed + survived)` only for a positive fully reconciled population with no unresolved outcomes.
- Keep killed, survived, timeout, no-test, skipped, crash, interrupted, suspicious, untested, and unaccounted outcomes distinct.
- Zero mutants, missing metadata, and unresolved populations do not produce 100% or a fabricated zero efficacy. Retain outcome counts while withholding an invalid efficacy value.
- Do not treat unresolved mutants as killed or equivalent, pool unlike profiles/runs, or rename a contribution profile as full-project test efficacy.

### Findings, execution, and debt

- Keep vulnerability advisories, affected dependencies, severity counts, analyzer findings, waivers, and configuration counts in their original units.
- A zero-finding claim requires a completed valid scan, not just a successful parent CI job.
- Show accepted exceptions and report-only severities without calling them resolved defects.
- A dependency dry run is a proposal, not an applied improvement.
- Report actual test execution events such as passed, failed, errored, and skipped from native results. Distinguish repeated executions from unique test identities. Reconcile totals; do not infer unique test counts from CI job names.

### Complexity, derived risk, and coupling

- Complexity is the analyzer's measured value at its actual function/module grain, not an invented percentage.
- For CRAP, state the exact variant. The statement-coverage variant is `CC^2 * (1 - coverage_fraction)^3 + CC`, requiring the same function's own coverage and complexity from matching source/run inputs.
- Missing/ambiguous function coverage remains unmeasured. Label a maximum as maximum observed and disclose measured/unmeasured/unknown populations. A reference such as CRAP 30 is informational unless the producer explicitly enforces it.
- Define graph grain and edges. CA is distinct incoming dependencies; CE is distinct outgoing dependencies. `CE / (CA + CE)` is undefined at zero degree.
- Do not relabel package-level values as file-level values, infer runtime coupling from a static import graph, or call a high-degree node a proven architectural defect.

## 6. Write a visual contract before drawing charts

Choose chart types from the data and reader's task. Document, for each image:

- Purpose and the question it answers.
- Included metrics and their exact normalized-model fields.
- Axis orientation, units, scale, limits, tick values, baseline, and any transformation.
- Bar/point/segment meaning and whether displayed values are raw, rounded for text, or transformed for positioning.
- Threshold/reference definitions, comparator direction, margin bands, and informational versus enforced status.
- Handling for unavailable/partial data, zero values, outliers, and clipped ranges.
- Ordering, stable IDs, maximum displayed rows, omitted-count label, and complete text/index location.
- Titles, profile/scope, commit/run/attempt labels, legend, accessibility, export sizes, and local/CI/fixture identity treatment.

Use the project's approved visual conventions where available. Otherwise implement the baseline design below and adapt it only when the data or project design requires a documented change. Do not substitute decorative gauges, radar charts, 3D effects, or an unexplained scorecard.

## 7. Primary measurement image

Create one compact primary dashboard for the small set of actual headline KPIs selected during inspection. AVO's reference design uses three vertically stacked horizontal panels: coverage, duplication, and mutation. Adopt those panels only when they are selected project metrics; do not install new checks merely to fill the picture.

For a selected metric whose current execution lacks evidence, preserve its panel with a neutral unavailable state and reason. A metric that is deliberately not part of this project's model need not occupy a placeholder panel. Explain omitted categories in the report.

Each panel must include:

- Accurate metric name and unit; measured value or an explicit availability label.
- Its own clearly labeled numeric axis and visible zero baseline for bar encodings.
- Scope/profile and whether higher or lower is better.
- The actual frozen minimum/maximum policy as a labeled reference marker when available.
- A textual margin interpretation when color conveys threshold distance.
- Enough precision to reveal the relationship between the raw value and threshold. Do not round the value solely to make it appear above the line.

Use independent panels for different scopes or scales; do not compare bar length across panels as if it were a shared quality score. Coverage and mutation can use a 0–100% scale. A small duplication percentage may use a separately disclosed zoomed range beginning at zero, with the ceiling and observed value visible. Never truncate an overflow silently; expand the axis or mark the clipped value explicitly.

Unavailable values have no measured bar. Use a neutral treatment with the reason. If a valid measurement exists but the policy is unavailable, show the actual value with neutral policy coloring. Do not render either case as a green zero.

Keep PASS/FAIL badges in the decision view. The measurement image may describe raw distance to a threshold, which can differ from the recorded gate's rounded comparison.

### Default threshold-margin coloring

If this project has no approved margin-color convention, use the following AVO-inspired convention for percentage panels and document it as visual interpretation, not enforcement:

- For a minimum threshold `t` and raw value `x`: red when `x < t`; yellow when `t <= x < t + 0.25 * (100 - t)`; green when `x >= t + 0.25 * (100 - t)`.
- For a maximum threshold `t` and raw value `x`: red when `x > t`; yellow when `0.75 * t < x <= t`; green when `x <= 0.75 * t`.
- Handle minimum 100% and maximum 0% explicitly: only the exact valid boundary meets the extreme policy. Unknown or invalid policy/value is neutral.
- Add textual labels such as below minimum, near minimum, above minimum margin, above maximum, near maximum, or below maximum margin. Do not rely on color alone.

These colors must not change gates. If the recorded policy rounds coverage to an integer before comparison, a raw 67.6% might pass a 68% floor while the raw-value chart remains below the line. Retain both facts and explain the precision rule. Do not invent that rounding policy for a project that does not use it.

## 8. Supporting views with explicit meanings

Implement the applicable views supported by actual evidence, keeping them secondary to the primary measurements. Do not force unavailable graph/function analysis into the report or turn reference visuals into new checks.

### Gate decision view

- Show each existing gate once, grouped by the producer's profile/component if needed.
- Use equal-size categorical badges or rows, with readable status, enforcement mode, policy summary, evidence verification state, and reason.
- Preserve failures, errors, invalid evidence, skips, cancellation, timeout, not-run, and unavailable distinctions.
- A claimed PASS with missing required proof must visibly say incomplete/unverified.
- Show accepted debt and non-blocking findings alongside the applicable policy.
- Required CI jobs belong to a separate execution population. Do not add their badges to a count of code-quality measurements or use gate outcomes as bar lengths/percentages.

### Mutation source view

- Use real source identities and stable path-sorted IDs with a complete path/index mapping.
- Show per-source efficacy only for valid complete source populations. Show outcome counts and missing/incomplete reasons for other sources.
- Keep aggregate enforcement separate: an aggregate profile floor displayed on source rows is an informational reference, not a new per-file gate.
- If there is no existing display policy, show at most 12 rows: missing/incomplete first, then lowest valid efficacy, with stable path ordering to break ties.
- State how many rows are omitted. Provide every source and outcome in the text/structured index.
- Reconcile source totals with aggregate evidence before presenting a coherent combined view.

### Complexity and derived-risk hotspots

- Use separate rankings for complexity and CRAP/other risk metrics. Do not put incompatible units on one numeric axis.
- Identify each function by source path, definition location, and qualified identity.
- Default to the highest 10 observed values per ranking, descending by value with deterministic path/location/name tie-breaking, unless the project already has a different approved policy.
- Label the chart as an excerpt and provide a complete source/function index.
- Disclose total known population, measured/unmeasured counts, and unknown population when parsing is incomplete.
- Distinguish informational references from actual enforced limits. Complexity and CRAP are related inputs, not interchangeable labels.

### Coupling/dependency view

- Use the actual graph grain: file/module, package, service, or another explicitly defined population.
- For a CA/CE scatterplot, put CE/outgoing on the horizontal axis and CA/incoming on the vertical axis. Label both axes with raw count units.
- Include isolated real nodes in population and median calculations. Distinguish namespace/group containers from actual files.
- Preserve coincident points with stable group markers and complete membership indexes; do not silently hide overlapping nodes or use unexplained jitter to change apparent degrees.
- If using median reference lines, calculate medians from the declared complete raw population and define equality handling. These lines describe relative connectivity, not architectural correctness or gate policy.
- Prefer ordinary clearly labeled scales. If reproducing AVO's specialized equal-area quadrant view, explicitly disclose the piecewise `log2(1 + count)` spacing centered at each raw median, keep raw-count tick labels, and test zero/median/overlap handling. Do not copy transformed positions and label the axes linear.
- Avoid labels such as good/bad architecture, stable/unstable design quality, or god class solely from graph position. State static/dynamic/external-edge limitations.

### Other project-specific views

For security severity, test outcomes, performance, size, or domain KPIs, choose a visual suitable to the actual unit and observed population. Do not combine unrelated dependency scanners into an invented vulnerability total, use a stacked outcome chart when populations do not reconcile, or claim a trend from a single run.

Historical trends require compatible semantic versions, scopes, environments/profiles, and policies, with clear revision/run labels. Break or annotate the series when comparability changes. Do not replace missing history with interpolated measured values.

## 9. Build readable reports and reproducible image artifacts

Produce the project's native human-readable report, a machine-readable normalized readout, actual image files, and complete indexes for truncated supporting views. Choose file formats and locations that fit existing tooling; no specific chart technology is required.

The main report should present:

1. Overall readiness/certification status, required actions, and evidence completeness. A successful renderer is not successful quality certification.
2. Full tested revision/run/attempt/profile identity, and head/base distinction where relevant.
3. The primary image with an equivalent accessible measurements table.
4. Gate decisions with policy and evidence state.
5. Execution results and actual test event counts, kept separate.
6. Applicable supporting views and full-index links.
7. Accepted debt, exclusions, unavailable inputs, limitations, and artifact/source references.

Use precise labels, legible typography, sufficient contrast, readable decimal precision, color-blind-safe cues, and no color-only meaning. Prevent overlapping text, cropped values, missing fonts/glyphs, illegible legends, and giant unnecessary whitespace. Long paths must remain resolvable through stable IDs or complete indexes.

Render charts programmatically from the normalized data. Do not use generative image synthesis to draw numbers, charts, labels, or status badges. Do not deliver a static mockup as if it were a measured report.

Ensure deterministic ordering, scales, transformations, IDs, and calculation behavior for the same evidence/configuration. Use source-run timestamps rather than the renderer's current clock as measurement identity. Resolve required fonts/assets locally or through the project's reproducible build process.

Bind each image to the exact normalized series and evidence identity it depicts, through embedded metadata or a verified companion manifest appropriate to the format. Retain image content hashes. A renderer/uploader/linker must not pair current text with a stale image from another run.

Produce previews for valid passing values, near-boundary values, failing values, and unavailable/partial evidence. Mark synthetic fixture previews clearly. Inspect the actual rendered images at desktop and narrow/mobile viewing widths, fix visual defects, and retain preview artifacts. A successful image-save operation alone is not visual verification.

## 10. Separate rendering from publication and quality execution

Provide a project-native report-generation command accepting an evidence location and output location. Its ordinary mode consumes recorded evidence without network access or producer execution. Add explicit identity/profile selection or strict validation options where necessary to avoid ambiguous selection.

Keep report building, optional publication, and quality-check execution separate. Publication may use the project's existing CI summary, artifacts, change-request comments, release snapshots, or another established channel. Do not introduce public hosting, a chart-storage branch, source commits on every run, a new credential, or an external service merely to display a picture.

If CI delivery is part of this repository's workflow:

- Place the reporting job after the required producer jobs and download evidence from that exact run/attempt.
- Attempt diagnostic report generation after producer failures when possible; do not require all gates to pass before reporting why they failed.
- Preserve prerequisite/required-check outcomes independently of reporting success.
- Use existing least-privilege publication mechanisms. Untrusted external contributions must not receive privileged secrets. Provide summary/artifact/text fallback when privileged publication is unavailable.
- Keep repository, tested revision, change-request head/base, run, attempt, and profile identity visible.
- Recheck current change-request identity before a write where the provider supports it. A stale or canceled run must not overwrite the current report. Label historical run reports explicitly.
- Follow the project's existing comment policy. If none exists, use one identified report per run, with retries updating only that run's entry; do not create separate spam comments per gate.
- Keep image-upload/link receipts tied to the image hash, normalized series, repository, revision, run/attempt, role, and verified returned URL.
- Use actual current-run artifact URLs. Explain authentication/retention constraints and do not pretend an artifact-download link is a durable inline image.
- Do not let one failed supporting view remove valid text/indexes or unrelated views.

Do not claim an external repository setting or successful hosted publication was completed unless it actually was completed under authorization. If publication needs an unavailable capability, finish local rendering, downloadable artifacts, CI summaries where possible, and document the exact remaining step.

## 11. Define fallback and failure behavior

Failure must leave truthful, usable information:

- Invalid measurement evidence produces an unavailable/partial value with its reason; it does not silently disappear from a selected metric.
- A renderer failure retains valid normalized data and text tables. Preserve the reporting error and any required reporting-job failure.
- A normalization/builder failure should produce a minimal text fallback from safely validated run/job facts where possible. Do not publish an apparently complete partial normalized artifact or chart.
- A failed upload retains local images, normalized data, text tables, and actual artifact links where available.
- Comment/summary permissions or service failures retain downloadable/local output and an explicit delivery status.
- Delivery fallback must never clear a failed gate, invent green readiness, conceal missing evidence, or certify an unsupported profile.

Document separate exit/status semantics for report generation, publication, and underlying quality readiness. A report can be successfully generated about failed gates; its quality-status field must still show failure. If CI requires successful reporting as an additional check, implement that separately and transparently.

## 12. Verify semantics with independent numerical cases

Write focused tests using the project's existing infrastructure. Verify normalization and exact expected values, state transitions, chart-series content, labels, references, ordering, and identity. Test independently calculated results rather than only the renderer's current output.

Include applicable cases below. The numbers are test inputs, not recommended production thresholds:

- Coverage `68/100 = 68%` at floor 68 is at the boundary; under the stated default margin convention it is yellow. `76/100 = 76%` is the green-margin boundary.
- Raw coverage `169/250 = 67.6%` stays 67.6 in the data and below the 68 marker. It may have a recorded PASS only if the supplied frozen producer policy actually rounds it to pass.
- Coverage `0/100 = 0%` is a measured zero. `0/0`, covered greater than total, missing counts, and invalid source proof are not valid zero scores.
- Duplication `3/200 = 1.5%` at ceiling 2 is green under the default margin rule; `151/10000 = 1.51%` is yellow; `2%` is yellow; `2.01%` is red. None becomes `98%` or a generic quality score.
- Valid `0/100` duplicated lines is measured 0%. Missing scan evidence is unavailable. Contradictory native percentage/counts must be rejected under the declared tolerance.
- Complete mutation `killed=2, survived=3, total=5` is 40%. Under a 40% minimum it passes; color remains a separate margin interpretation.
- Mutation `killed=2, survived=3, total=6` is incomplete because one outcome is unaccounted. Do not report 40%, 50%, 0%, or 100% as complete efficacy.
- Zero-mutant, timeout/no-test/crash, unknown-category, negative-count, conflicting-alias, and source-versus-aggregate mismatch cases retain their actual reasons and withhold unsupported efficacy.
- For statement-coverage CRAP: `CC=6, coverage=0` yields 42; `CC=10, coverage=0.5` yields 22.5; `CC=10, coverage=1` yields 10. Missing same-function coverage produces no score.
- For CA/CE: `CA=2, CE=3` gives instability 0.6 with point `(3,2)`; `CA=0, CE=0` gives undefined instability and an isolated point, not invalid coordinates or a zero-valued quality score.
- A recorded gate PASS with missing/changed execution proof displays incomplete/unverified, not green certification.
- Valid zero security findings differs from an offline or failed audit.
- A failed gate with valid measurements remains visible; successful report generation does not change its result.
- Repeated test executions, skipped/failed/error events, conflicting totals, and partial native result files are handled according to the documented execution-event contract.
- Wrong run/attempt/commit/profile, changed artifact bytes, stale image metadata, incompatible schema, and unsafe artifact paths cannot populate a current report.
- Missing threshold, extreme 0%/100% thresholds, out-of-range values, and a raw rounding/decision discrepancy render without misleading bands.
- Long labels, empty/all-unavailable views, coincident graph points, rank ties, top-N truncation, omitted counts, and complete index membership are verified.
- Renderer/upload/publication failure paths preserve text/data and original quality failures.

Keep reviewed semantic definitions and fixed expected outputs separate from generated execution snapshots. Do not regenerate expected arithmetic, policy, chart baselines, or semantic definitions from production output during normal testing. A changed screenshot alone is not proof of correctness; an unchanged screenshot alone is not proof of accurate values.

Run the relevant tests, generate an actual report from real project evidence, and visually inspect rendered output. Validate that image, text table, normalized readout, and publication manifest agree on values, state, scope, threshold, and identity. Follow project-required design approval gates where they exist; do not invent an extra approval ceremony.

## 13. Acceptance and final handoff

The implementation is complete when:

- Reporting is an independently runnable consumer of saved evidence.
- Every displayed value is traceable to validated inputs and a documented definition.
- Measurements, gates, execution, and configuration remain separate.
- Charts follow an explicit verified visual contract and actual rendered images are provided.
- Missing/partial/stale evidence and presentation failures are represented honestly.
- Applicable supporting views have complete text/structured indexes.
- Local and CI delivery fit the project's existing structure and permissions.
- Tests cover independent arithmetic, boundary/state cases, provenance, fallbacks, and visual-series consistency.
- Documentation explains commands, evidence requirements, image semantics, publication behavior, retention, and known limits.

Finish with changed components, exact report commands, tests/real evidence used, report/image/index locations, visual-verification results, and any actual unresolved evidence or delivery limitation. Distinguish local previews, synthetic fixtures, and published CI results. Do not claim a mocked or unexecuted upload was successful.

## AVO reference: adapt the reporting principles

AVO's active reference reporting design separates a primary raw-percentage dashboard from categorical gate decisions, execution results, configuration diagnostics, and supporting source-indexed views. Its primary chart shows coverage, direct duplication percentage, and mutation efficacy on separate panels. Supporting views include function complexity/CRAP, file coupling, source-level mutation, and gate decisions, backed by complete text and structured indexes.

AVO freezes policy and run identity in evidence, validates captured command/artifact provenance, uses one normalized series for text and images, and keeps text usable when rendering or publication fails. Its retained legacy chart generators are not automatically the active design.

Adapt those principles to this project's real metrics, evidence, and approved visuals. Do not copy AVO's tooling, thresholds, source paths, mandatory view count, mutation scopes, security policy, credentials, or CI-provider-specific publication implementation.
