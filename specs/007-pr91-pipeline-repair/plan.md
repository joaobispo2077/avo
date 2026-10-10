# Implementation Plan

Baseline: `11545c1`, current branch `feature/avo-ways`.

## Audit and reporting

Restore cycle-safe advisory traversal and lockfile version lookup, retain critical-only blocking, and collect every unresolved critical hit. Keep npm-audit-summary.json fields ok/critical/high/moderate/low; add reported records and execution error. Keep deps-findings.json findings and add error. Unknown measurements use null. Preserve fixture and report compatibility. Refresh artifacts before validation and after every outcome.

Add --all to the existing Python entry point, running pip-audit with existing documented ignores before npm. Keep npm-only and --record-pip compatibility. Route npm quality:deps and the shell wrapper through --all. Preserve pip failure status and distinguish malformed or unavailable evidence from vulnerabilities.

Override Handlebars at 4.7.10, regenerate only the affected lockfile entries with npm 11.3.0, and smoke-test release-note generation without publishing.

## Media setup and regression

Use one generic CI media-tool setup script in the three existing jobs. Reuse working binaries; otherwise install without recommended extras, with bounded retries and a three-minute step timeout. Verify FFmpeg, FFprobe, lavfi, libx264, AAC, FFV1, and PCM used by generated fixtures.

Extend neutral generated-media fixtures to connect initial-cut planning, real native rendering, exact review lineage, explicitly marked test review/approval, candidate snapshots, reconstruction, actual cleanup, and final wrap. Negative boundary cases retain existing stale-source, absent-map, and candidate-isolation coverage; add partial deletion to the connected regression. Only fix production runtime behavior if reproduced.

## Validation and delivery

Run audit/report tests first, then focused native media and boundary regressions. Run core pytest, npm unit, and full quality; retain coverage >=68%. Confirm the actual installed Handlebars version and release-note rendering. Remote CI success remains pending until an approved commit is submitted; do not claim local checks establish remote success.

Prepare separate documentation, audit tests, proof tests, audit repair, dependency override, and CI provisioning commits. Show staged groups and proposed Conventional Commit messages and wait for approval. Do not create branches, publish, tag, or update changelog.
