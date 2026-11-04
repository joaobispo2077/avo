# Prompt 1: Implement project-specific quality gates and KPIs

Copy the prompt below into an AI agent working in the target repository. It is self-contained. Run Prompt 2 separately when the evidence-producing commands are ready.

---

You are working in the current project. Implement a reliable, maintainable quality-gate and KPI system that developers can run locally and through this project's continuous integration system.

Complete the implementation and validation. Do not stop after an audit, recommendations, a tool list, or a plan. Choose the implementation from the actual project structure, risks, existing tools, and conventions. No language, framework, package manager, testing library, CI provider, reporting service, or commercial product is prescribed.

## 1. Scope and boundaries

This task owns quality policy, executable checks, measured inputs, local commands, CI enforcement, and versioned machine-readable evidence.

It does not own dashboards, charts, generated report images, pull-request comments, report websites, image hosting, or a reporting application. Those belong to a separate reporting task. Native tool output, actionable terminal diagnostics, execution logs, test result files, and structured evidence are required here and are not a reason to build a presentation layer.

Build the smallest complete solution that fits this repository. Reuse existing commands, configuration, dependencies, CI jobs, and test infrastructure before introducing new components. Do not build a universal quality platform or a configurable plugin framework for hypothetical future projects.

Preserve product behavior, public interfaces, architecture, source data, and unrelated work. Follow project instructions and branch policy. Do not create or switch branches, publish releases, change repository protection settings, or add credentials unless the user or existing project instructions authorize those actions. Implement the checks that can be completed without those external changes and document any remaining administrative step.

## 2. Inspect the current project before designing gates

Read the applicable agent instructions and relevant project decisions first. Inspect the actual execution paths, rather than choosing tools from a generic checklist.

Identify and document:

- The project's purpose, users, deliverables, and highest-impact failure modes.
- Languages, runtimes, build systems, dependency manifests, lockfiles, and supported operating systems.
- Applications, libraries, services, packages, infrastructure, generated code, vendored code, examples, fixtures, and external project data.
- The real source roots and which directories belong to production, tests, tooling, documentation, generated output, and disposable cache.
- Current architecture and enforced dependency boundaries. Derive boundaries from existing design and code; do not invent layers just to add an architecture checker.
- Existing lint, formatting, type checking, build validation, test, coverage, security, dependency, performance, and domain-specific checks.
- How those checks are invoked locally and in CI, including wrappers, working directories, environments, prerequisites, and exit-code handling.
- Unit, integration, end-to-end, contract, property, mutation, platform, and manual tests that actually exist. Identify tests that require private data, hardware, paid services, production credentials, or unavailable infrastructure.
- CI triggers, job dependencies, required checks, concurrency, cancellation, retry behavior, caching, artifact retention, and trust boundaries for external contributions.
- Existing thresholds, baselines, exceptions, suppressed findings, exclusions, and documented reasons.
- Existing machine-readable outputs and report consumers that must remain compatible.

For a monorepo, map responsibilities and coverage by component. Do not assume one language's tool measures every component. Avoid scanning generated artifacts or dependencies while accidentally excluding important first-party source.

Use a fresh inspection or baseline execution to distinguish current behavior from stale documentation. Record the files and commands supporting your conclusions. If a check cannot run, record the actual limitation; do not assume it passes.

## 3. Define the quality model before implementation

Keep these four concepts separate throughout configuration, code, evidence, and documentation:

1. **Measurement/KPI:** an observed value with a defined population, unit, calculation, and evidence. Example: 742 covered executable lines out of 1,000, or 74.2% line coverage.
2. **Gate decision:** the application of an explicit policy to valid evidence. Example: coverage must be at least the configured floor.
3. **Execution result:** whether a command or CI job completed, failed, errored, timed out, was canceled, was skipped, or did not run.
4. **Configuration/debt diagnostic:** configured exceptions, suppressed rules, planned dependency changes, or architecture contracts. Configuration counts are not automatically observed findings or improvements.

A successful command is not a 100% quality measurement. A configured threshold is not the observed value. An unavailable measurement is not zero. A job marked successful does not prove that every required tool ran or produced valid evidence.

Do not invent a composite quality score, average unrelated percentages, label all passing checks as a KPI, or claim that static checks prove complete correctness, security, or good architecture.

Create a concise implementation matrix before editing. For every proposed check or KPI, specify:

- Stable identifier and human-readable name.
- The project-specific risk or decision it supports.
- Current implementation to reuse, or the smallest justified addition.
- Exact source scope, exclusions, unit, population/grain, and aggregation rule.
- Authoritative command and policy configuration location.
- Measurement definition and validity requirements.
- Enforcement mode: blocking gate, warning, informational measurement, or not applicable.
- Threshold/comparator, precision/rounding, and exception policy where applicable.
- Local/PR/full/scheduled/release profile and expected runtime budget.
- Structured evidence to produce and how it will be verified.
- Initial status: existing, missing, partially available, or unsupported, with a reason.

Briefly explain the choices, then implement them. Ask a focused question only when a material policy choice cannot be resolved from the repository or user instructions. Continue independent work while clarification is pending.

## 4. Select checks according to project risks

Evaluate the categories below. They are a selection guide, not a mandate to install every tool or introduce every KPI.

- Build, compilation, packaging, configuration/schema validation, and installation smoke checks for the deliverables the project actually ships.
- Static lint and formatting in check-only mode.
- Type or contract validation where the language and existing code make it useful.
- Unit and integration tests, with a small number of end-to-end checks for critical user flows when justified.
- Line, branch, function, or other coverage supported by actual instrumentation. Label each separately.
- Complexity and maintainability diagnostics at the function/module level that the analyzer actually measures.
- Duplicate-code detection with explicit file/token/line scope and comparison rules.
- Dead-code findings with confidence levels and justified exceptions, accounting for dynamic entry points and framework conventions.
- Architectural/import boundaries, forbidden dependencies, or cycle checks grounded in the current design.
- Dependency vulnerabilities and, where relevant, first-party security analysis, secret detection, container/infrastructure checks, or dependency-license policy. Use the project's threat model and approved policies.
- Dependency-lock consistency, reproducible installation, dependency-tree health, or install/build footprint where relevant.
- Mutation or property-based testing for critical logic when supported and affordable. Start with a calibrated scope rather than the entire repository by default.
- Performance, memory, latency, size, or resource budgets only where a representative workload, repeatable environment, and meaningful baseline can be defined.
- Accessibility, visual regression, API compatibility, database migration safety, data quality, model evaluation, or other domain-specific checks when the project requires them.

Document why major categories are included, deferred, or not applicable. A CLI does not automatically need browser tests; a frontend does not automatically need a backend's mutation setup; a data pipeline needs checks that reflect data correctness. Existing suitable checks should remain authoritative.

Do not create deployment-frequency, lead-time, incident, defect-escape, customer-satisfaction, or other organizational/product KPIs from local code scans. Such metrics require their own real data sources and are outside scope unless the project already exposes them and the user requests them.

## 5. Specify precise measurement semantics

For each implemented KPI, document the formula, raw counts, denominator, exclusions, units, validity rules, and limitations. Preserve raw observations so a later reporter can reproduce the displayed value without rerunning analysis.

Apply these rules when the corresponding metric is selected:

### Coverage

- Identify the measured kind: executable-line, statement, branch, function, or another supported kind. Do not rename one kind as another.
- A line/statement percentage must use the tool's matching covered and executable counts: `100 * covered / total` with a positive denominator.
- Preserve raw counts and sufficient precision. Store the tool's authoritative comparison/rounding behavior separately from display formatting.
- Do not infer branch coverage from line coverage or substitute repository-wide coverage for a particular function's coverage.
- Report a zero-sized, missing, inconsistent, or uninstrumented population as unavailable/not applicable according to explicit policy, never as 100% coverage.
- A test failure may leave useful partial coverage, but partial execution must remain disclosed and must not satisfy a gate that requires a completed successful test run.

### Mutation testing

- Record the source scope, active profile, mutation operators/configuration, relevant tool version, and all outcome categories.
- If adopting AVO's complete-verdict definition, efficacy is `100 * killed / (killed + survived)` only when the positive total population is fully reconciled and every mutant has a killed or survived verdict.
- Preserve timeouts, crashes, skipped, no-test, interrupted, suspicious, untested, unaccounted, and other tool-specific outcomes as distinct unresolved categories. They are not killed mutants or proven equivalent mutants.
- Zero mutants is not a successful 100% score. Unknown or conflicting outcome categories must not disappear during parsing.
- If the project already uses another documented mutation-score convention, preserve and label it explicitly; do not silently switch denominators or compare unlike definitions.
- Do not pool different source scopes, profiles, operators, runs, or revisions into a single score without an explicit valid aggregation contract.
- Prevent restored caches and old aggregate files from becoming fresh execution evidence. Verify cached inputs and require a current execution/export contract.

### Duplication

- Record whether the metric counts duplicated lines, tokens, blocks, or another unit, and what the denominator includes.
- For a duplicated-line metric, preserve `duplicated_lines`, `total_lines`, and `100 * duplicated_lines / total_lines`, plus clone locations where available.
- Document whether overlap is counted once or per match. Validate counts and consistency with the native tool's percentage within a declared tolerance.
- This is a lower-is-better measurement with a maximum policy if enforced. Do not transform it into `100 - duplication` and call it the same KPI.

### Findings and structural diagnostics

- Keep advisory counts, affected-package counts, source findings, severity counts, exceptions, and unique vulnerabilities distinct. Do not add unlike populations into a misleading defect total.
- A completed valid scan with zero findings can produce a measured zero. Missing output, an offline scan, a parser error, or an incomplete scan cannot.
- Preserve finding identity, location/dependency path, severity/confidence, remediation information, and matched exception context where available.
- A dependency-tree dry-run proposal is not an applied fix or a measured reduction in defects.
- For coupling, name the graph and grain. If using CA/CE, define CA as distinct incoming dependencies and CE as distinct outgoing dependencies at that grain. Record deduplication, self-edge, dynamic/external import, and isolated-node treatment. `CE / (CA + CE)` is undefined when the denominator is zero.
- For CRAP or another derived risk metric, define the exact variant and join inputs at the same function/source revision. For the statement-coverage variant, `CRAP = CC^2 * (1 - coverage_fraction)^3 + CC`. Do not substitute file/repository average coverage for function coverage. Missing inputs leave the function unmeasured. An informational reference is not a blocking gate.

Never coerce malformed counts, negative values, contradictory totals, non-finite numbers, or missing fields into valid measurements. Check the domain and type of values rather than accepting any value a parser can convert.

## 6. Calibrate policies without gaming the baseline

Preserve existing valid thresholds and authoritative configuration. Do not weaken a gate, narrow its scope, delete failing tests, reduce test populations, or add broad exclusions simply to make the first run green.

Where a policy is missing:

1. Measure the current state and identify the risks that matter.
2. Separate immediately enforceable correctness/safety invariants from maintainability improvement targets.
3. Choose a justified initial policy using existing project expectations, observed baseline, analyzer limitations, and acceptable runtime.
4. Use informational measurement or a documented no-regression ratchet for established debt when an immediate absolute gate is not justified. Define exactly how comparable old/new findings are matched.
5. Make any provisional policy explicit. Do not silently approve all current findings as permanent exceptions.

For every exception, retain an exact scope/identifier, reason, owner or review route, and review/expiry condition appropriate to project conventions. Detect stale exceptions where practical. Keep accepted debt visible in evidence. Do not automatically renew waivers or rewrite baselines during ordinary verification.

Policy must have one authoritative source. Local checks, CI checks, evidence capture, and later reports must use that same policy or a frozen copy identified with the run. Avoid duplicating thresholds in scripts, workflow files, test expectations, and documentation.

## 7. Produce a versioned evidence contract

Create or extend the project's existing structured artifact format. Choose a native, maintainable representation; no particular serialization technology is required. Document its schema and compatibility/versioning rules. A later reporting task must be able to consume a saved evidence directory without invoking the quality tools.

At minimum, preserve these logical fields, either directly or through verified references:

### Run identity

- Schema version, project/repository identity, and execution mode: local, CI, or fixture.
- Unique run identifier and retry/attempt identity where relevant.
- Full tested source revision. For change-request validation, preserve head/base identity separately from the actual tested merge/revision.
- Dirty-worktree state and source-content fingerprints for local execution. Do not present a local modified tree as proven clean-commit evidence.
- Profile, component scope, exclusions, UTC start/end timestamps, duration, relevant environment/tool versions, and configuration/lock/source fingerprints.
- The required gate/job set and policy snapshot/revision used by this execution.

### Per-check execution

- Stable check ID, exact command/arguments and working directory, with secret values redacted.
- Whether execution started and completed, its actual exit code/signal, and its outcome/reason.
- A log reference and content hash, and produced-artifact references with hashes/sizes and availability reasons.
- Before/after fingerprints or equivalent checks sufficient to detect source/configuration changes while measuring.
- Explicit entries for planned required checks that did not run. Absence must not be interpreted as success.

### Measurements and findings

- Stable metric ID and semantic revision, name, classification, unit, grain, scope, and calculation identifier.
- Raw counts/inputs, derived value when valid, completeness, measurement availability state, and a reason when not fully measured.
- Links to native evidence, source locations, input fingerprints, and the execution that produced the observation.
- Measured/unmeasured/unknown population counts where relevant.
- Frozen comparator, threshold, precision/rounding, and exception policy for any associated gate.
- Recorded gate decision, enforcement mode, reason, and relationship to execution/evidence validity. Keep these separate from the measurement value.

Use explicit state dimensions rather than an overloaded green/red flag. Preserve completed, failed, error, skipped, canceled, timed-out, not-run, partial, invalid, missing, unsupported, and not-applicable meanings where they occur. Define mappings for native tool statuses. Use an unavailable value with a reason instead of a fake numeric zero.

Use fresh, isolated output locations per run/attempt, or an equally reliable cleanup/manifest scheme restricted to owned generated outputs. File modification time alone does not establish provenance. Verify identity, scope, hashes, and produced-file membership before accepting old outputs or caches.

Store raw inputs and captured results even when a threshold fails, to the extent the tool provides them. Evidence-writing failure must not erase the original command failure. Required certification must reject absent/invalid required evidence under an explicit documented rule; optional unavailable diagnostics must not silently become new blockers.

Keep logs and artifacts free of credentials, private source data, and unnecessary absolute machine paths. Bound artifact paths to the owned output root and reject path traversal. Generated run data should follow the repository's ignore/retention conventions rather than being committed on every run.

## 8. Implement local commands with truthful behavior

Provide discoverable project-native entry points for:

- Each individual check.
- The fast everyday quality profile.
- Relevant test suites and coverage.
- A fuller or slower profile when justified.
- Evidence production/validation as part of these executions.

Names and tooling should match this repository. Do not introduce another command runner merely to imitate an example.

Checks must be non-destructive by default: formatting checks do not rewrite source, dependency checks do not apply upgrades/hoists, and verification does not regenerate accepted baselines. Keep explicit fix commands separate if the project already offers them.

Preserve failure propagation through wrappers, pipelines, log capture, and aggregate commands. A blocking check failure, required tool crash, or required missing prerequisite must produce a failing overall result. If independent checks continue to collect diagnostics after a failure, the final result must still fail. If execution stops early, record later checks as not run.

Do not silently download large tools, call paid services, mutate production systems, or use private datasets to run the default profile. Separate optional/heavy/infrastructure-dependent profiles, document setup, and accurately label unsupported local environments. An unsupported required check is not a local PASS.

Set realistic timeouts and clean up child processes. Keep parallel jobs from writing the same result files. Use existing locked/reproducible environment setup and include relevant test/tool dependencies.

## 9. Integrate CI without changing what success means

Extend the existing pipeline rather than creating a disconnected parallel quality system.

- Reuse the same check implementations and policy as local execution. Explain unavoidable platform/profile differences.
- Schedule cheap deterministic checks on the normal contribution path; place expensive calibrated checks on an appropriate full/scheduled/manual path unless they are already required.
- Preserve existing required-check names and branch behavior where external settings may depend on them.
- Make the intended dependency graph explicit: prerequisite/setup, relevant checks/tests, and final required readiness/aggregate result.
- Ensure required readiness cannot become green when a dependency failed, errored, timed out, was unexpectedly skipped, or supplied invalid required evidence.
- Avoid blanket success overrides, unchecked error suppression, and fallback paths that convert failure into success. Diagnostic collection may continue while the required result remains failed.
- Upload/preserve available evidence and logs after failed checks when the CI platform permits it. Canceled/hard-killed runs may be incomplete; label them honestly.
- Keep run/attempt identity on artifacts. Do not accidentally combine sibling jobs from different runs, merge/head revisions, profiles, or retries.
- Use least-privilege permissions and existing credentials. Untrusted contributions must not gain access to privileged secrets because quality checks were added.
- Treat cache reuse as an optimization, not proof of current execution.
- Document time budgets and artifact retention. If branch-protection changes are required, state the exact required check names and the administrative action; do not claim those settings were changed without doing so under authorization.

Do not add report rendering, image uploading, comment publishing, or a dashboard job in this task. Leave a clear consumer boundary for Prompt 2.

## 10. Test the quality system itself

Add focused tests using the project's existing test infrastructure. Validate independent expectations, not only that the current implementation agrees with itself.

Cover applicable cases:

- A real pass and a real threshold failure; below, exactly at, and above each threshold.
- Authoritative rounding behavior versus retained raw measurements.
- Valid zero findings versus missing/invalid/incomplete scan evidence.
- Zero or inconsistent denominators, negative counts, contradictory totals, unexpected statuses, and non-finite values.
- Failing tests, partially produced outputs, required tool absence, command errors, timeouts, and cancellation where practical.
- Exit-code propagation through the individual command, wrapper, umbrella command, and final CI readiness logic.
- Stale output, mismatched revision/run/attempt/profile, changed source/configuration, and invalid artifact hashes.
- Exceptions that match, do not match, exceed their allowed ceiling, expire, or become stale.
- Monorepo/component scope and intentional exclusions.
- Mutation zero-population/unresolved-accounting behavior if implemented.
- Local/CI policy consistency and compatibility with existing consumers.

Use synthetic fixtures with manually verifiable expected counts/formulas and at least one controlled failing command. Keep reviewed expected policy/semantic fixtures separate from generated run data. Do not have tests rewrite expected values from production output or automatically accept a changed baseline.

Run the relevant new tests and the repository's required validation. Execute the implemented local profile against the actual project. Exercise the CI path where access allows; if hosted CI has not run, distinguish locally validated workflow wiring from a successful hosted run. Report real existing failures rather than weakening policy to claim completion.

## 11. Documentation, acceptance, and handoff

Document in the project's normal locations:

- Architecture/scope of the quality system and why the selected checks fit this project.
- Commands, profiles, environment setup, runtime expectations, and local/CI differences.
- The gate/KPI matrix, exact metric definitions, authoritative policy, thresholds, exclusions, exceptions, and limitations.
- Artifact layout, schema, identity/validity rules, and compatibility behavior.
- How to reproduce a failure, inspect evidence, review an exception, and intentionally revise a threshold/baseline.
- CI job dependencies, required-check names, retention, and any outstanding external setup.

The work is complete when the selected checks are implemented, local/CI entry points share policy, failures propagate correctly, evidence is available for a separate consumer, meaningful tests cover the contracts, and the documentation matches actual behavior. A generated configuration file or a green wrapper around unexecuted tools does not satisfy acceptance.

End with a concise implementation summary and a reporting handoff containing:

1. Files/components changed and the project-specific rationale.
2. Exact commands and profiles, with what you actually ran and their results.
3. The gate/KPI matrix and authoritative configuration references.
4. The evidence-root location and schema/semantic versions.
5. One real saved evidence run, plus the independent fixtures needed to validate a reporter.
6. Which measurements are available, partial, informational, deferred, or unsupported.
7. Any unresolved failures or external setup, without claiming unexecuted CI success.

## AVO reference: principles to adapt, not a required stack

AVO is an example of a project that combines local commands with CI checks for lint, formatting, test coverage, complexity, dependency security, dead code, duplication, import boundaries, and dependency-tree diagnostics. It uses a cheaper mutation profile for contribution checks and a separate fuller profile. Its command captures bind outcomes and artifacts to source/run identity; later reporting consumes that evidence.

At the inspected AVO revision, example policies included a 68% coverage floor, a 2% duplicated-line ceiling, and 40%/50% light/full mutation floors. These are historical project-specific examples, not recommendations or defaults for this project. Do not copy AVO's values, source paths, tool choices, profile scopes, security severity policy, or CI provider without independent justification.

The transferable design is: inspect the project, define each measurement precisely, apply explicit project-specific policies, run the same checks locally and in CI, retain trustworthy structured evidence, and leave presentation to a separate consumer.
