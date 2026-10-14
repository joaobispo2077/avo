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
