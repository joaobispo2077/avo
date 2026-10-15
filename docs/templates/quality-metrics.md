# Quality metrics snapshot

`docs/quality-metrics.md` is not maintained by hand. The release cut
(`.github/workflows/release.yml`) writes it from the unified `quality-metrics`
artifact for the exact tip SHA and CI run.

The cut fails when that JSON is missing, not overall PASS, any Software
quality gate is not PASS, or the JSON is bound to a different SHA. It does
not re-run gates and does not reuse the previous release's numbers. Ordinary
pull requests do not write the file. A dry-run with no releasable version
does not write the file and does not fail the workflow.

One optional dashboard PNG lands in `docs/quality/charts/<version>/` only at the
cut. Its embedded series must match the JSON and the tables. Schema 1 historical
readouts retain their original seven-image validation.

Current schema 2 snapshots require complete mutation accounting, the frozen
profile/floor, and matching commit/run identity, plus successful mandatory jobs
and readiness. Unfinished or stale evidence cannot satisfy a green release cut.
The snapshot does not invent a score or change floors. See
[quality reporting](../quality-reporting.md).

Current reports separate observed measurements and their raw-input proof from
gate decisions and required-job outcomes. The versioned measurement extension
includes function CRAP/complexity and static CA/CE diagnostics; CRAP reference 30
is informational. Raw capture logs, input counts, source locations, exact artifact
URLs and SHA-256 references support each available value. Historical records
without captures identify that limitation rather than inventing evidence.
