# PR 108 CI failures

The push and pull-request runs at `9e0294a` failed for two independent reasons.
The always-run CI readiness check correctly failed after those jobs; it needs
no policy change.

## Protected audio boundaries

Ubuntu's FFmpeg 6.1.1 changed the first sample of a protected dialogue interval
because `aeval` time values rounded across its start boundary. The native
regression compared the entire protected PCM region, including its first sample.
The same test passed with the workstation's FFmpeg 7.1.1, hiding the version
difference locally.

The shared dialogue treatment command now evaluates time as `n/s`, using the
evaluated sample index and sample rate documented by
[FFmpeg](https://ffmpeg.org/ffmpeg-filters.html#aeval). Both the untouched and
repaired masks use that same clock. Filter calibration, window boundaries,
channel policy, approval requirements and loudness processing are unchanged.
The byte-for-byte assertion remains strict, with mono and stereo coverage.

A minimal audio-only build from the official FFmpeg 6.1.1 source reproduced
the failure: one changed protected sample at index 24,000. The fixed command
preserved all protected samples and full PCM duration for both mono
(288,000 bytes) and stereo (576,000 bytes).
The build and synthetic evidence live only in ignored scratch space.

## Runner setup timeout

The other job stopped before tests: FFmpeg package downloads from the Ubuntu
runner mirror exceeded the three-minute installation limit. All four callers
of `ensure-ffmpeg.sh` now allow eight minutes for setup. The unit job allows
twenty minutes overall, retaining time for its tests and smoke checks. Integration,
software-quality and branch-risk jobs already have larger overall budgets.
Download retries, network timeouts and the real codec smoke checks remain active.

The first remote validation at `07b35ea` passed unit tests, software quality
and light mutation tests. Integration setup still timed out after eight minutes,
and one fresh-runner retry reproduced the slow package transfer. The successful
unit runner fetched the same 62.8 MB in four seconds. Increasing the timeout
alone therefore did not resolve the mirror variability.

When installation is necessary and the runner's APT mirror list exists,
`ensure-ffmpeg.sh` now replaces only the Azure Ubuntu mirror URL with Ubuntu's
main HTTPS archive before refreshing indexes and installing packages. Unrelated
mirror entries remain unchanged. A missing mirror-list file keeps the existing
APT configuration. This changes only the disposable runner's package source;
package signature verification, retries, setup budgets and codec checks remain
active. A Linux regression executes the real helper with temporary source files
and mocked package commands for HTTP, HTTPS and absent-list cases.
The Linux regression passes all three cases; the focused workflow contract suite
passes 30 tests. Shell syntax and Python lint checks also pass.

## Dependency gate

The previous local dependency audit reported 37 findings across three package
families. The frozen lock now selects certifi 2026.10.23, opentelemetry-api 1.45.1
and Pillow 13.0.0 on Python 3.11+. Auditing an export of the frozen development
and MCP requirements found no known vulnerabilities on Python 3.11. No advisory
exceptions, gate thresholds or direct dependency requirements were weakened.

Pillow 13 requires Python 3.11+. CI runs Python 3.12. The project still supports
Python 3.10, whose lock resolution retains Pillow 12.3.0 and its outstanding
advisories. This fix does not silently drop that Python version or claim its
dependency set is vulnerability-free; it needs a patched compatible release
or a separately approved minimum-Python change.

## Validation

- Exact FFmpeg 6.1.1 synthetic comparison: old expression fails, fixed expression passes.
- Focused audio, preparation and workflow contract suite: 61 passed.
- Ruff lint/format and complexity gate: passed.
- Frozen requirements audit on Python 3.11: no known vulnerabilities.
- Full core suite: 3,555 passed, 20 skipped, 3 deselected.
- Full unit suite with refreshed dependencies: 3,423 passed, 2 deselected.
- Complete `npm run quality`: passed, including 3,423 coverage tests and 75%
  total coverage (68% required), dependency audit, complexity, dead code,
  duplication, architecture contracts and dependency-tree checks.
- Node audit: no critical findings; two high and two moderate findings remain
  under the existing noncritical policy.

The remote checks cannot exercise these local fixes until their commits are
approved and pushed. Commit approval remains separate from implementation.
