# AVO CI/CD (agent-facing)

Dense reference for the GitHub Actions pipeline and local gate commands. User-facing
summary: README **Built on** section only; this doc is for agents and maintainers.

Quality reporting feature 010 keeps existing gates, thresholds and selection.
New current PR runs use separate report comments; retries refresh that run's
comment. Fatal report construction retains dependency-independent text and the
original failed job outcome. Local indexed coupling/CRAP previews require owner
review before supporting images are enabled in CI. Definition and fixed-case
snapshots detect reviewed semantic/policy changes without per-run Git writes.

The approved mutation and gate-decision views add optional `quality-mutation`
and `quality-gate-decisions` archives/native images. Mutation retains per-source
outcomes and raw metadata from the existing execution; the collector verifies
their hashes and aggregate totals. The light/full floors remain aggregate-only.
Gate badges show categorical outcomes, existing policy and execution proof;
required CI jobs remain a separate execution population. All five image roles
retain independent text/artifact fallbacks and the same current-PR/cancel guards.
Release snapshots continue to require only the primary dashboard.

## Standard CI validation model (+ software quality)

AVO is an **orchestrator**. CI must validate **external toolchain prerequisites**
before asserting the repo itself is usable. **Software quality** (lint, coverage,
complexity, audits, …) is part of the **standard `ci.yml` pipeline** — not a
separate workflow. Local umbrella: `npm run quality`. See
[software-quality-audit.md](./software-quality-audit.md).

| Lane | Script / job | What it checks |
| --- | --- | --- |
| **Gate 1** | `scripts/validate-prerequisites.sh --ci` | GitHub Spec Kit (`.specify`), video-use engine, ffmpeg (warn in CI), watch-skill, HyperFrames, optional clones — see `avo.dependencies.json` |
| **Unit tests** | `scripts/ci/run-unit-tests.sh` | AVO core unit pytest (`not project and not integration`); Python via `uv sync --frozen --extra dev` |
| **Integration tests** | `scripts/ci/run-integration-tests.sh` | `tests/integration` runtime/subprocess boundaries; requires ffmpeg in CI |
| **Software quality** | `quality-lint.sh` + `quality-format.sh` + `run-coverage.sh` + `quality-complexity.sh` + `quality-deps.sh` + `quality-deadcode.sh` + `quality-duplication.sh` + `quality-architecture.sh` + `quality-tree.sh` (job `Software quality` in `ci.yml`) | Lint/format **fail-immediately** (Ruff C901 ≤ **31**); coverage fail-under **68%** on the **unit** suite only (`--ignore=tests/integration`); complexity xenon max-absolute **B** + `complexity-allowlist.json`; deps block unwaived Python advisories and npm criticals (`check_npm_audit.py` / `deps-audit-allowlist.json`; npm high, moderate, and low reported); deadcode vulture min_confidence **60** + `deadcode-allowlist.json`; duplication jscpd threshold **2%** (`.jscpd.json`); architecture import-linter `.importlinter`; tree health `npm find-dupes` (command failure fails; hoist plan report-only). Python via `uv sync --frozen --extra dev --extra mcp`. Local: `npm run quality:*` / `test:coverage` |
| **Gate 2** | `scripts/validate-usability.sh --ci` | `avo.config.json`, provider scaffolds, `setup.sh --dry-run`, scaffold scripts — after Gate 1 + unit tests + software quality |
| **CI readiness** | `scripts/ci/check_ci_readiness.py` | Always-run check within selected full CI; all six mandatory jobs must succeed |
| **Quality report** | `scripts/ci/write_unified_quality_report.py` | One commit/run-bound summary, dashboard, diagnostics, and release artifact after readiness |

Order in `.github/workflows/ci.yml` is enforced via job `needs:`.

Unit and integration lanes run in parallel after Gate 1. Software quality does
not run `tests/integration`; coverage is the unit suite only.

Gate 1 also validates all GitHub Actions workflows with actionlint 1.7.12,
including expression context availability. ShellCheck and Pyflakes are disabled
in this check; the existing quality gates own source linting. Run the same check
locally before pushing workflow changes:

```sh
docker run --rm -v "$(pwd):/repo" --workdir /repo rhysd/actionlint:1.7.12 -shellcheck= -pyflakes=
```

The default integration suite includes code-drawn browser capture tests alongside
the other runtime tests. Its setup installs the optional capture dependency,
Chromium, and the pinned brush asset so missing prerequisites fail CI instead of
silently skipping capture coverage. Playwright uses its standard browser cache;
no job-level browser path override is needed. Engine packaging retains its
separate platform smoke tests and checks historical tags without requiring
features those tags did not contain.

The code-drawn decoder uses `-fps_mode passthrough`, supported by FFmpeg 7 and
9; the removed `-vsync` option must not be used in this path. Integration tests
exercise the packaged Canvas, SVG and brush starters with both opaque and
transparent output and require exact decoded RGBA. The brush starter initializes
its lazy graphics resources before `avoReady` resolves, then redraws each seek
from the recorded seed. Brush portability checks isolate only the brush cache,
leaving the installed browser location intact.

The generic brush starter uses seeded marker strokes rather than the vendor's
watercolor fill, which can vary between identical seeks on software graphics.
Its opaque and transparent starters are tested with SwiftShader explicitly,
alongside the default graphics backend. This changes only newly scaffolded
starters; existing compositions retain their source, and exact RGBA checks
continue to reject nondeterministic output.

### Run selection and duplicate suppression

CI validates PRs targeting `develop`, `release`, or `main`. Push triggers cover
`feature/**` and `release`; `develop` and `main` use PR validation only. Engine
binary keeps its existing path filters and PR triggers, but push builds run only
on `feature/**`. Its published-release and manual build/upload paths remain.

Both workflows use a lightweight selector before their expensive jobs:

| Event | Full execution |
| --- | --- |
| Eligible PR | Always, including drafts; existing checks and path filters apply |
| Feature push without an eligible open PR | Run the existing full workflow |
| Feature push with an eligible open PR at the exact current head | Suppress the duplicate push execution; the PR owns validation |
| CI push to `release` | Always run, even while a promotion PR is open |
| Engine published-release or manual dispatch | Run the existing freeze/smoke and optional release upload |

The selector matches repository, head branch, and full current head SHA before
suppressing a feature push. CI accepts replacement PRs only when their base is
`develop`, `release`, or `main`; Engine accepts any PR base because its PR
trigger has no branch filter. Draft PRs count. An API error or uncertain lookup
keeps the full push execution. A fresh PR lookup must also confirm `mergeable:
true`; conflicts or unknown mergeability retain full push validation because
[GitHub does not start PR workflows with merge conflicts](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#pull_request).
An intentionally suppressed push publishes no
measurements or successful quality report. Selected full CI keeps the existing
job names, gate commands, thresholds, and strict readiness evaluation.

Concurrency supersedes older feature-push and PR updates within the same
workflow, event, and branch/PR. It does not use cross-event cancellation to choose
between push and PR evidence. Release CI and Engine published-release/manual
runs use unique run groups and are not cancelled by this deduplication policy.
If a full feature run starts before a PR opens, it may overlap the initial PR
run; subsequent pushes use the PR execution. This opening race is bounded, and
the two runs retain their own identities.

The release exception is required: `release.yml` consumes a successful **push**
CI run and its artifacts for the exact release-tip SHA and run ID. A PR's
synthetic merge evidence cannot replace that certification. Engine release
publication builds its zips in its own release/manual run rather than consuming
an earlier protected-branch push build.

### Branch protection — required checks (task-013)

On `develop` / `release` / `main`, require these
**exact** GitHub Actions check names (job `name:` fields from `ci.yml`):

| Required check name | Job id | Role |
| --- | --- | --- |
| `Gate 1 — Orchestrator prerequisites` | `prerequisites-gate` | Toolchain prerequisites |
| `Unit tests (AVO repo)` | `repo-unit-tests` | AVO core unit pytest + install/hf smokes |
| `Integration tests (AVO repo)` | `repo-integration-tests` | `tests/integration` subprocess/runtime lane |
| `Software quality` | `software-quality` | **Phase-1 fast gates** (lint, format, coverage, complexity, deps) + deadcode, duplication, architecture, tree — fail-immediately |
| `Mutation tests (light)` | `mutation-light` | Scoped mutmut after unit tests (**20-minute** timeout); complete validated outcome accounting and profile floor (Ubuntu); evidence feeds the unified report |
| `Gate 2 — Project usability` | `usability-gate` | Project usability; `needs` includes `software-quality` |
| `CI readiness` | `ci-readiness` | Full-run readiness check; skipped, absent, failed, or cancelled mandatory jobs do not pass |

Do **not** require a separate Gate 3 / quality workflow check — software quality is
the `Software quality` job inside workflow **CI**.

### Related workflows (expected paths)

| Workflow | Role |
| --- | --- |
| `ci.yml` | Standard CI: Gate 1 → unit tests ∥ software quality → Gate 2; light mutation job after unit tests |
| `mutation-full.yml` | Weekly + dispatch full mutation (slow lane) |
| `size-signal.yml` | Informational PR size/weight signal (non-blocking) |
| `dependency-graph.yml` | Weekly self-contained HTML dependency table + DOT export for `src/avo`; SHA/UTC/scope recorded |
| `watch-skill-smoke.yml` | Manual/weekly watch-skill invoke (beyond Gate 1 clone) |
| `quality-toolchain-smoke.yml` | Manual/weekly ruff/xenon/mutmut/jscpd CLI smokes |

Drift lock: `tests/test_quality_matrix.py` asserts npm quality script names,
`ci.yml` quality job + hard lint/format/coverage/complexity/deps steps, coverage
fail-under 68, frozen dev dependencies on unit jobs and dev + MCP on quality jobs, Phase-1
blocking posture (`usability-gate` `needs` `software-quality` + required check
name **`Software quality`**), no separate Gate 3 workflow file, slow-lane
workflow basenames, **20-minute** mutation timeouts, run-scoped quality PR
comments and removal of the mutation sticky, and Node 24 / Node 24 action majors.
Linux jobs pin `ubuntu-24.04`.

Each current PR run gets a `quality-gates-report-<run_id>` comment with overall status, commit/run
identity, required actions, one dashboard, a measurements table, a gate-decision
table, an execution table, and collapsed diagnostics. The dashboard plots raw
coverage/duplication/mutation percentages on separate scales; thresholds belong
to the gate policies. The collector joins
current-run producer artifacts after readiness; stale or incomplete evidence
cannot yield PASS. Image failures preserve the text table. Existing Software
quality and mutation checks remain separate. See
[quality reporting](quality-reporting.md) for evidence and schema details.

### Measurements, gates, and execution evidence

The measurements table reports observed values with their scope, input counts,
artifact files, and SHA-256 references. The gate table retains all nine fast
checks and light mutation, their policies, and PASS/FAIL decisions. The execution
table records required job outcomes and observed unit/integration testcase
counts. Configured exceptions and import-contract definitions are diagnostics;
their configured counts are not measured findings or executed checks.

CI runs each fast check through `scripts/ci/run_quality_gate.py`. Under
`reports/quality/gates/<gate>/`, `gate.json` records the exact argument list,
commit/run identity, UTC timestamps, duration, command exit code or signal, log
hash, produced-file hashes, and source fingerprints before and after execution.
`gate.log` captures combined stdout/stderr. The wrapper preserves command
failure; it does not soften any gate. Missing or old outputs have an explicit
reason and cannot provide a successful zero measurement.

The `quality-evidence` artifact contains these captures and measured inputs:

| Input under `reports/quality/` | Observed evidence |
| --- | --- |
| `coverage.json` | Unit-suite executable/covered statement counts and raw coverage |
| `jscpd/jscpd-report.json` | Duplicated/total source lines and clone pairs |
| `complexity.json` | Measured block locations, cyclomatic scores/ranks, actually matched exception reasons/ceilings, unwaived or worsened findings, stale entries, and scan errors |
| `deadcode.json` | Actual Vulture locations, kinds/confidence, matched exception reasons, unwaived findings, stale entries, and scan errors |
| `pip-audit-raw.json`, `npm-audit-raw.json` | Sanitized audit JSON, advisory details/fix versions, dependency paths, exact commands, provenance, and frozen audit policy; unrun/error scans remain explicit |
| `deps-findings.json`, `npm-audit-summary.json` | Blocking findings and npm severity totals under the existing Python/npm policy |
| `dependency-tree.json` | Actual npm dry-run add/remove/change proposals, without applying them |
| `code-risk.json` | Informational function complexity/CRAP inputs and package CA/CE counts |

Unit and integration CI use `PYTEST_ADDOPTS` to capture native JUnit events in
`unit-tests.xml` and `integration-tests.xml`. Their receipts/logs and XML are
uploaded as `unit-test-evidence` and `integration-test-evidence` even after a
failure, when files exist. `test_execution_evidence.py` counts actual passed,
failed, error, and skipped testcase events independently of the job result.
Failed or interrupted executions can supply partial counts; absent or invalid
XML supplies no count. These are test execution observations, not a repair-success
percentage.

The publisher downloads the exact current-run producer artifacts and rechecks
identity and file hashes. Artifact URLs come from the corresponding upload
actions. A successful job cannot substitute for a missing receipt or changed
measurement file; local captures with a local run identifier remain local
preview evidence.

### Informational function and package diagnostics

`measure_code_risk.py` computes function/method CRAP from measured cyclomatic
complexity and that function's own statement coverage:
`CC² × (1 − covered statements / statements)³ + CC`. The coverage capture must
have succeeded for the same SHA/run, with the recorded raw coverage hash and
unchanged source fingerprints. Repository/file averages do not replace function
coverage. Unmatched, ambiguous, excluded, and zero-statement functions remain
unmeasured; the summary labels its maximum **max observed** and reports both
measured and unmeasured function counts. Reference 30 is informational and adds
no gate or floor.

The static import graph also measures CA (distinct incoming packages) and CE
(distinct outgoing packages), aggregated at `avo.<package>`, plus instability
`CE / (CA + CE)`. A package without edges has undefined instability. Within-package
edges and dynamic imports are outside this measurement. These review
signals do not establish god classes; abstractness remains unmeasured. The separate
file-level quadrant uses static module edges, actual-file median references and
indexed coincident positions. Its descriptive regions add no gate. Complexity
and CRAP review views retain complete source-indexed Markdown/JSON, with partial
and unknown populations explicit. Existing xenon B/exception ceilings, Ruff C901 ≤31, coverage
68%, duplication 2%, and mutation 40%/50% policies continue to determine gates.

### Publishing the report

CI creates a `quality-gates-report-<run_id>` PR comment for every new current run with measurements,
gate decisions, evidence, commit/run identity, and one inline dashboard. It does
not commit generated charts or write to repository branches. The report job
keeps `contents: read`, `actions: read`, and `pull-requests: write`; the existing
bot identity creates/updates the run-specific comment. A retry refreshes only
that run's comment and latest-attempt label; earlier distinct-run reports remain
historical. Failed mandatory jobs still produce an honest current report.

`scripts/ci/upload_quality_chart.py` verifies the dashboard PNG against the
current commit/run and normalized measurements before uploading it as a native
GitHub attachment. Its receipt binds the returned URL to the image digest and
commit/run identity. The offline report linker embeds only a matching receipt.
The report job references the existing `RELEASE` environment with
[`deployment: false`](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idenvironment),
accessing its existing `GH_TOKEN` secret without creating deployment records.
The uploader receives that credential through the private environment alias
`QUALITY_CHARTS_TOKEN`; this is not a separate secret. No new token, secret, or
credential copy is needed. Supported user credentials include OAuth, classic
PATs, and fine-grained PATs with repository write access. The installation
`GITHUB_TOKEN` cannot upload attachments and remains the bot comment publisher's
credential; token restrictions follow the
[official GitHub CLI client](https://github.com/cli/cli/blob/v2.102.0/internal/attachments/client.go#L65).
Only trusted repository runs may use the upload credential. Fork PRs do not
receive it and retain the text report and artifact-download fallback.

The normalized JSON and raw dashboard PNG remain Actions artifacts. Their
downloads require GitHub sign-in and follow the existing 14-day retention
period. Native image attachments are separate from these artifacts and do not
inherit that expiry. Missing credentials, authentication/network failures, or
missing/stale image evidence leave explicit unavailable notes and preserve the
text report and available downloads. The historical `ci/quality-kpi-charts`
storage branch should not be merged as a source feature.

After owner preview review, the same full report also produces optional
`quality-hotspots` and `quality-coupling` archives, each containing a complete
Markdown/JSON index and its PNG when rendering succeeds. Selected feature and
release pushes retain these archives; native attachments remain PR-only. Each
native role has its own immediate freshness check, fixed filename, independently
validated receipt and download fallback. One role failing leaves the other views
and inline text useful. Fatal report-builder fallback uploads only readable text.
The existing release image requirement remains `dashboard.png` alone.

A release cut writes `docs/quality-metrics.md` from that push's green unified
JSON for the exact SHA and run. Pull-request greens do not write that file.

Only `pull_request` runs publish the native dashboard and sticky comment.
Publication checks that the PR remains open, its head and base still match the
run, and the run has not been cancelled. Stale or cancelled runs leave the
existing comment intact. Feature and release push runs retain their own job
summaries and downloadable artifacts without overwriting PR merge evidence.
Size-signal remains a separate sticky: packed/unpacked bytes and file count only
— no `npm pack` file listing. Publish steps `continue-on-error` so a fork without
comment permission does not fail the gate.

## Manifests

| File | Role |
| --- | --- |
| `config/avo.config.json` | Job routing (which tool owns which stage) |
| `config/avo.dependencies.json` | Gate 1 — pinned repos, clone paths, required vs optional |

Every `job` in `config/avo.dependencies.json` must exist under `config/avo.config.json` → `jobs`.

## Release automation

- Config: [`release.config.mjs`](../release.config.mjs) (semantic-release plugins)
- Workflow: `.github/workflows/release.yml` runs after **CI** succeeds on `release` (stable), or by manual dispatch
- Secret: `GH_TOKEN` with `contents: write` (see [versioning.md](./versioning.md))

### Release-cut quality metrics snapshot

`release.yml` writes `docs/quality-metrics.md` only when
a release cut runs (semantic-release has a version to publish). The snapshot
is its own job. It checks out the green CI head SHA (the release tip) and
downloads artifact `quality-metrics` for that **exact tip
SHA and CI run**. It fails the job if that JSON is missing, not overall PASS, bound to
a different commit/run, or any mandatory check or policy-bearing gate measurement is not PASS. Informational
CRAP and CA/CE observations do not introduce release thresholds. There is no soft
warning that still publishes. The job does
not re-measure gates and does not copy the previous release's numbers.
When the dry-run has no next version, the snapshot job exits without writing
`docs/quality-metrics.md` and does not fail the workflow.

`workflow_run` loads `release.yml` from the default branch. A merge to
`develop` does not change the workflow the next cut executes. This job runs
on a cut only after the file is on `main`.

Every selected full CI run publishes unified measurement evidence and one
dashboard. Only a release cut writes `docs/quality-metrics.md`. Reporting does
not change floors or replace gates.

The optional dashboard PNG from the same run is copied to
`docs/quality/charts/<version>/`. Its embedded series must match the JSON and
tables or the cut fails. Missing images leave tables only.

Schema 2 mutation evidence must match the frozen profile/floor, SHA, and workflow
run, with complete integer outcome accounting. Incomplete evidence cannot
satisfy a green current release snapshot. Schema 1 historical readouts remain
supported, without satisfying current run-bound validation.

Template note: [`docs/templates/quality-metrics.md`](./templates/quality-metrics.md).

## Workflows (maxframe-style layout)

| Workflow | Trigger | Purpose |
| --- | --- | --- |
| `ci.yml` | PRs targeting `develop`/`release`/`main`; push to `release` or `feature/**` | Selector suppresses duplicate feature pushes with a matching open PR; selected full runs keep Gate 1 → unit tests + `hf:doctor` ∥ software quality → Gate 2 and light mutation. Release push certification always runs. |
| `mutation-full.yml` | weekly + `workflow_dispatch` | Full critical-package mutation (mutmut); artifacts |
| `size-signal.yml` | PR | Informational pack/install footprint (non-blocking) |
| `dependency-graph.yml` | weekly + `workflow_dispatch` | Optional HTML dependency table + DOT export (`quality:dep-graph`), with SHA/UTC/scope provenance |
| `watch-skill-smoke.yml` | weekly + `workflow_dispatch` | watch-skill clone + CLI/help invoke |
| `quality-toolchain-smoke.yml` | weekly + `workflow_dispatch` | ruff, xenon, vulture, pip-audit, lint-imports, mutmut, jscpd |
| `setup-smoke.yml` | `workflow_dispatch` | Full `setup.sh` on ubuntu + windows |
| `orchestrator-smoke.yml` | manual + weekly cron | Gate 1 (+ optional) + Whisper tiny model + Gate 2 |
| `ffmpeg-whisper-smoke.yml` | `workflow_dispatch` | Binary/import smoke (like maxframe `yt-dlp-smoke.yml`) |
| `release.yml` | After **CI** on `release` (+ manual) | semantic-release dry-run → publish, then `workflow_dispatch` Engine binary to attach platform zips (`GITHUB_TOKEN` does not fire `on: release`). The snapshot job checks out the green CI head SHA. With a next version it hard-fails unless that SHA's Software quality JSON is PASS, then the publish job commits `docs/quality-metrics.md`. No next version exits without writing the file and does not fail the workflow. `workflow_run` reads this file from the default branch. |
| `engine-binary.yml` | Existing path-filtered PRs; path-filtered `feature/**` pushes; `workflow_dispatch` (`attach_tag`); `release: published` | Selector suppresses duplicate feature builds with a matching open PR on any base. PyInstaller zip smoke and release/manual zip + SHA256SUMS upload remain. |

Reference: [maxframe workflows](https://github.com/joaobispo2077/maxframe/tree/main/.github/workflows).

## Local reproduce

```bash
npm ci
# Quality/unit CI path (locked — matches ci.yml repo-unit-tests + software-quality):
uv sync --frozen --extra dev --extra mcp
# Gate 2 still uses unlocked editable without extras in CI:
# pip install -e .

# Gate 1 (orchestrator prerequisites)
npm run validate:prerequisites -- --ci
# or: bash scripts/validate-prerequisites.sh --ci

# Gate 2 (project usability — run after Gate 1 passes)
npm run validate:usability -- --ci

# Software quality (ci.yml job — Phase-1 hard + Phase-2 deadcode)
npm run quality:lint
npm run quality:format
npm run test:coverage
npm run quality:complexity
npm run quality:deps
npm run quality:deadcode
npm run quality:duplication
npm run quality:architecture
npm run quality:tree
npm run quality:dep-graph
# Slow lanes (Ubuntu for mutmut):
# npm run quality:mutation
# npm run quality:dep-graph
# or full umbrella (Phase 1 + structure gates):
# npm run quality

# CI unit tests (AVO core; after uv sync, or via npm which uses uv run --frozen)
bash scripts/ci/run-unit-tests.sh
# or: npm run test:unit
```

Windows:

```powershell
npm run validate:prerequisites -- --ci
npm run validate:usability -- --ci
```

## CI constraints

- **No Whisper model download** on the PR path (`ci.yml`). Model prep runs only in
  `orchestrator-smoke.yml` / `setup-smoke.yml`.
- **watch-skill**: shallow-cloned in Gate 1 when missing (`--ci`).
- **ffmpeg**: WARN in CI if absent (Node `ffmpeg-static` satisfies npm scripts).
- **Optional tools** (`ai-memory`, `ai-jail`, `logo-generator-skill`): skipped unless
  `--include-optional`.

## Environment variables

| Variable | Meaning |
| --- | --- |
| `AVO_CI=1` | Set in workflows; reserved for future setup-script CI behavior |
| `PY` / `PYTHON` | Override Python binary for gate scripts |
| `QUALITY_CHARTS_TOKEN` | Private uploader environment alias for the existing `GH_TOKEN` secret in `RELEASE`, not a new secret. Used only for trusted native dashboard uploads; fork PRs retain text and artifact downloads. |
| `NODE_VERSION` | `24` in all workflows (npm/eslint/jscpd). GitHub-owned actions are Node 24 majors (`checkout@v6`, `setup-node@v6`, `setup-python@v6`, `cache@v5`, `upload-artifact@v7`). `astral-sh/setup-uv@v10.2.0` runs on Node 24 (`runs.using: node24` since v7). Workflows that already set `enable-cache: true` keep that explicit value. `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24` covers leftover third-party JS actions. |
| Linux runner | `ubuntu-24.04` on every Linux job under `.github/workflows/` (including the engine-binary Linux matrix entry). Pinned so those jobs do not follow `ubuntu-latest` onto Ubuntu 26. Windows stays `windows-latest`. Engine macOS stays `macos-14`. |

## Branch protection (block merge until CI passes)

`develop`, `release`, and `main` should require these **CI** job checks before merge. GitHub
shows them under the commit/PR checks tab with these exact names:

- `Gate 1 — Orchestrator prerequisites`
- `Unit tests (AVO repo)`
- `Integration tests (AVO repo)`
- `Software quality`
- `Mutation tests (light)`
- `Gate 2 — Project usability`
- `CI readiness`

In selected full CI, `CI readiness` always evaluates all six mandatory jobs,
including integration and light mutation. A failed, cancelled, skipped, or
missing result fails readiness;
a skipped dependent Gate 2 cannot make a failed upstream job mergeable. PRs into
`develop` run the same checks as PRs into `release` and `main`. The integration
lane installs the MCP extra, and missing MCP dependencies fail its runtime smoke
in CI instead of silently skipping it. Local environments may still skip that
optional smoke when MCP is absent.

### GitHub UI

1. **Settings → Rules → Rulesets → New branch ruleset**
2. **Target branches:** `develop`, `release`, `main`
3. Enable **Require status checks to pass**
4. Add the **seven** job names above, including **`CI readiness`** and **`Integration tests (AVO repo)`**
5. Enable **Require branches to be up to date before merging** (recommended)
6. Save — set enforcement to **Active**

Remote rulesets must be inspected by a maintainer before rollout. This repository
change does not alter them. A delete/force-push restriction alone does not enforce
CI readiness.

### `gh` CLI (repository ruleset)

Run from a machine with admin access to `joaobispo2077/avo`:

```bash
gh api repos/joaobispo2077/avo/rulesets -X POST -f name="require-ci" -f target=branch -f enforcement=active -f bypass_actors='[]' -F 'conditions={"ref_name":{"include":["refs/heads/develop","refs/heads/release","refs/heads/main"],"exclude":[]}}' -F 'rules=[{"type":"pull_request","parameters":{"required_approving_review_count":0,"dismiss_stale_reviews_on_push":false,"require_code_owner_review":false,"require_last_push_approval":false,"required_review_thread_resolution":false}},{"type":"required_status_checks","parameters":{"strict_required_status_checks_policy":true,"required_status_checks":[{"context":"Gate 1 — Orchestrator prerequisites"},{"context":"Unit tests (AVO repo)"},{"context":"Integration tests (AVO repo)"},{"context":"Software quality"},{"context":"Mutation tests (light)"},{"context":"Gate 2 — Project usability"},{"context":"CI readiness"}]}}]'
```

After the first CI run on a PR, if a check name is missing from the picker, merge one
PR with CI green once — GitHub registers check names from completed runs.

Private repos on the free plan support rulesets; legacy branch protection API also works
but rulesets are easier for multiple branches.

## Adding a new orchestrated dependency

1. Add job to `avo.config.json` if new stage.
2. Add tool entry to `avo.dependencies.json` (repo URL, clone path, `required`).
3. Extend `src/avo/validate_dependencies.py` if new `kind` is needed.
4. Update `docs/install/README.md` setup order if setup.sh prepares it.
