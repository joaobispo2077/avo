# Feature Specification: Restore PR 91 Pipeline Reliability

**Feature Branch**: `feature/avo-ways`

**Created**: 2026-10-10

**Status**: Approved for implementation

**Input**: Restore reliable PR 91 validation, preserve the critical-only dependency policy, and verify proof, review, candidate, reconstruction, and cleanup behavior together.

## User Scenarios & Testing

### User Story 1 - Trustworthy validation (Priority: P1)

Maintainers need completed checks that enforce the established security policy and distinguish failed tests from insufficient coverage.

**Why this priority**: Incorrect audit results and stalled setup prevent safe merge decisions.

**Independent Test**: Run isolated audit cases and media-tool setup checks without footage projects.

**Acceptance Scenarios**:

1. **Given** an unwaived critical dependency finding, **When** validation runs, **Then** it fails and names the finding; lower severities remain visible without blocking.
2. **Given** unavailable, malformed, or error-only audit evidence, **When** validation runs, **Then** it fails with an execution diagnostic rather than reporting a clean audit.
3. **Given** missing media tools, **When** setup runs, **Then** it completes or fails explicitly within three minutes, without silently skipping required tests.
4. **Given** failing tests and sufficient coverage, **When** the report is generated, **Then** it identifies test failure without claiming the coverage threshold was missed.

### User Story 2 - Accurate dependency evidence (Priority: P1)

Reviewers need current dependency findings, advisory identities, installed versions, and dependency paths.

**Why this priority**: Reviewers must be able to reproduce the security decision and identify the repair.

**Independent Test**: Generate reports from controlled successful, failed, and skipped audit outcomes.

**Acceptance Scenarios**:

1. **Given** a transitive critical finding, **When** its dependency references are followed, **Then** the root advisory is identified without duplicate records or infinite cycles.
2. **Given** a critical finding without an advisory identity, **When** another finding has an exception, **Then** the unidentified finding still blocks.
3. **Given** an earlier failed run, **When** a clean run follows, **Then** earlier findings disappear from current evidence.
4. **Given** a skipped audit, **When** reports are generated, **Then** it remains skipped and does not display previous findings as current measurements.

### User Story 3 - Reliable proof and cleanup boundaries (Priority: P2)

Creators need canonical proofing, exact candidate review, and safe delivery cleanup to remain compatible.

**Why this priority**: These boundaries protect editorial meaning and reconstruction inputs.

**Independent Test**: Exercise the connected flow using short generated media and explicitly marked fixture review evidence.

**Acceptance Scenarios**:

1. **Given** an initial cut with intentionally absent later-stage maps, **When** a proof is produced, **Then** review binds to its exact canonical inputs and media.
2. **Given** changed sources or canonical inputs, **When** old evidence is reused, **Then** validation rejects it.
3. **Given** a reviewed candidate, **When** a fresh candidate is rendered, **Then** it does not inherit review or approval evidence.
4. **Given** an approved fixture delivery, **When** cleanup runs, **Then** reconstruction inputs remain and final metrics count only verified deletions.
5. **Given** partial cleanup, **When** final reporting is requested, **Then** it is rejected.

### Edge Cases

- Dependency cycles with and without an advisory exit; mixed identified and unidentified findings.
- Duplicate, expired, unused, mismatched, or incomplete exceptions.
- Audit errors after an earlier successful or failed invocation; missing installed-version information.
- One or both media binaries missing, unusable binaries, unavailable encoders, slow package downloads.
- Changed source bytes, absent-map revisions, stale executor evidence, fresh candidates, and partial deletions.

## Requirements

### Functional Requirements

- **FR-001**: Dependency validation MUST block unwaived critical npm findings, include development dependencies, and preserve the existing Python dependency policy.
- **FR-002**: The affected release-tool dependency MUST use the identified patched version without waiving the patched vulnerabilities or upgrading unrelated dependencies.
- **FR-003**: Validation MUST follow dependency references safely and report root advisories with available installed versions and paths.
- **FR-004**: Reporting MUST count affected package entries by severity independently from the blocking decision.
- **FR-005**: Exceptions MUST validate identity, reason, expiry, duplicates, and usage; unidentified critical findings cannot be waived.
- **FR-006**: Audit tests MUST assert the established policy and retain equivalent behavioral coverage.
- **FR-007**: Existing report consumers MUST retain their supported fields and receive actionable finding or execution-error diagnostics.
- **FR-008**: Unavailable audit measurements MUST be unknown rather than zero.
- **FR-009**: Every invocation MUST refresh its evidence; skipped checks MUST NOT reuse previous evidence.
- **FR-010**: Local and CI audit entry points MUST enforce the same policy while preserving npm-only invocation compatibility.
- **FR-011**: Setup MUST reuse usable media tools or install missing tools without optional package extras.
- **FR-012**: Installation MUST have bounded network retries and a three-minute limit without increasing existing job limits.
- **FR-013**: Required media binaries and encoding capabilities MUST be verified before tests; missing capabilities MUST fail setup.
- **FR-014**: A generated-media regression MUST connect canonical proofing, native execution, review lineage, candidate approval, reconstruction, cleanup, and final reporting.
- **FR-015**: Regression coverage MUST exercise stale input rejection, absent-map invalidation, fresh-candidate evidence isolation, partial deletion, and preservation.
- **FR-016**: Test review evidence MUST be explicitly marked as fixture evidence and MUST NOT approve real footage.
- **FR-017**: Runtime repairs MUST address reproduced failures within these flows and preserve public commands and timeline schemas.

### Editorial And Platform Requirements

- **ER-001**: Existing creator-intent, source ancestry, accessibility, and human-review gates MUST remain enforced.
- **ER-002**: Generated test media MUST contain no private footage or third-party rights dependencies.
- **ER-003**: Proofs MUST reconstruct from fingerprinted canonical sources; earlier exports cannot become substitute sources.

### Key Entities

- **Audit result**: Current findings, severity counts, exception decisions, and execution diagnostics.
- **Candidate evidence**: Exact proof, source, review, and approval bindings for one candidate.
- **Reconstruction bundle**: Preserved canonical dependencies required to reproduce a delivery.
- **Cleanup receipt**: Planned work and verified deletion outcomes for one project and master.

## Success Criteria

### Measurable Outcomes

- **SC-001**: All 11 baseline audit-test failures are resolved without reducing equivalent coverage.
- **SC-002**: All controlled critical, lower-severity, error, exception, and stale-evidence scenarios produce the expected decision and report.
- **SC-003**: Required media setup completes or reports an explicit failure within three minutes.
- **SC-004**: The 90 baseline focused regressions and the connected generated-media regression pass.
- **SC-005**: Required checks complete successfully on a fresh submitted revision; coverage remains at least 68% and required media tests execute.
- **SC-006**: Successful cleanup preserves all reconstruction inputs and reports exactly the verified removed bytes; partial cleanup cannot produce a final wrap.

## Assumptions

- Baseline is commit `11545c1` of PR 91, targeting develop.
- Scope is CI repair and feature regression boundaries, not a full roadmap audit or speculative refactoring.
- Existing sequential quality gating and human approval policies remain unchanged.
- No public timeline schema migration is required.
- Work stays on the current branch; commits require staged-group review and approval. No publishing, tags, or changelog updates are authorized.
