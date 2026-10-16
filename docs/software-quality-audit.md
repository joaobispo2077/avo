# AVO Software Quality Audit

**Task:** `avo-refactoring-software-quality` · **Date:** 2026-08-01

**Updated:** 2026-10-14

Agent- and maintainer-facing map of **what is tested**, **what is gated**, and **where
instructions live**. See also [software-foundation.md](./software-foundation.md) and
[ci.md](./ci.md).

---

## Audiences

| Audience | Primary entry | Quality expectation |
| --- | --- | --- |
| **AI agents** | `AGENTS.md`, `.cursor/rules/`, Copilot instructions | pytest + Gate 1/2 + `npm run quality` (Phase-1) before claiming orchestrator work done |
| **Maintainers** | `docs/ci.md`, `docs/launch.md`, this doc | Full pytest in CI; release tag alignment |
| **Human editors** | `docs/avo-workflow.md`, footage `edit/` QC | Editorial gates + engine contract tests |

---

## Validation gates

| Gate | Script | Validates |
| --- | --- | --- |
| **Gate 1** | `scripts/validate-prerequisites.sh --ci` | Spec Kit, engine, ffmpeg, watch-skill, HyperFrames, optional clones |
| **Gate 2** | `scripts/validate-usability.sh --ci` | `avo.config.json`, provider scaffold, setup dry-run, core helpers |
| **Software quality** | `npm run quality` (job in `ci.yml`) | Software-metric quality — lint/format, coverage floor, complexity, audits, structure (see concept table) |

**CI order (`ci.yml`):** Gate 1 → software quality ∥ unit tests (`not project`, ignore `tests/integration`) ∥ integration tests (`tests/integration`) → Gate 2.

**Release order:** successful CI → determine version → exact-run quality snapshot
→ version checks and semantic-release → GitHub Release.

Gate 1/2 behavior is unchanged. Software quality is **standard CI**, not a separate workflow.

---

## Software quality concepts

Concept-first dashboard: tools may swap; concepts and fail/pass criteria are the product.
Local umbrella: `npm run quality` (Phase 1 fast gates). Drift lock: `tests/test_quality_matrix.py`.
The unified report separates observed measurements, policy-based gate decisions,
and execution results. One dashboard shows raw coverage/duplication/mutation
percentages on separate scales; other units and source locations belong in the
measurements table and diagnostics. See [quality reporting](quality-reporting.md).

| Concept | What it proves | Current tool | Phase |
| --- | --- | --- | --- |
| Static lint / format | Machine-consistent Python + JS surface | Ruff; ESLint + Prettier + EditorConfig | 1 Must |
| Type safety | Contracts at boundaries (lint now; mypy ratchet later) | typescript-eslint; mypy phased | 1–2 |
| Test coverage floor | Product paths exercised under fail-under **68%** (line; baseline 2026-08-14, floor of ~68.5%) | pytest-cov (`src/avo`; `branch = false`) through `run-coverage.sh` | 1 Must |
| Complexity | New/worsened measured complexity above max-absolute B fails outside documented exception ceilings; C901 ≤ 31 | xenon via `quality-complexity.sh` / `check_complexity.py` + allowlist; Ruff C901 (`max-complexity = 31`) in lint | 1 Must |
| Function CRAP | Observed complexity and each function's statement coverage identify review candidates; reference 30 is informational | `measure_code_risk.py` + verified same-run `coverage.json`; complete function inputs in `code-risk.json` | Informational |
| Package CA/CE | Distinct incoming/outgoing package counts and instability describe static coupling | Reused internal import graph in `code-risk.json`, aggregated at `avo.<package>` | Informational |
| Dependency security audit | Unwaived Python advisories and npm criticals fail | `quality-deps.sh`: pip-audit including MCP runtime; `npm audit` critical via `check_npm_audit.py` + `deps-audit-allowlist.json` (npm high, moderate, and low reported); `@semantic-release/npm` file stub (`scripts/ci/semantic-release-npm-stub`) avoids nested vulnerable npm CLI bundles | 1 Must |
| Lock / install reproducibility | Frozen installs in quality/unit CI | `uv sync --frozen`; `npm ci` | 1 Must |
| Dependency tree health | Unexpected npm dupes / lock drift visible (`npm find-dupes` dry-run; command failure fails CI; non-empty hoist plan is report-only until `/evolve`) | `quality:tree` / `quality-tree.sh` (`npm find-dupes`); uv lock | 2 Should |
| Dead code | No unused weight outside allowlist | vulture (`check_deadcode.py`, min_confidence **60** + `deadcode-allowlist.json`) | 2 Should |
| Duplication | AI copy-paste blocked over threshold (**2%**; baseline ~1.09% lines 2026-08-14) | jscpd (`.jscpd.json` + `quality-duplication.sh`) | 2 Should |
| Architecture / import boundaries | Forbidden imports fail (layer map + grandfathered CLI/render/shorts/timeline→adapter edges) | import-linter (`.importlinter` + `quality-architecture.sh`); `helpers/` shims are outside `root_package = avo` | 2 Should |
| Visual dependency graph (DOT export) | Optional package dependency diagnostic, non-blocking for PRs | `dependency-graph.yml` + `quality:dep-graph` / `avo_dep_graph.py` (self-contained HTML table + DOT export; SHA/UTC/scope provenance; 14d) | 3 Should |
| Mutation testing | Tests catch wrong behavior — **light/PR** + **full/weekly** | mutmut Ubuntu; complete outcome accounting; **20-minute** light/full timeouts; selected validation/MCP files and calibrated timeline mapping in full; floors 40% / 50% (`mutation-config.json`) | 3 Must |
| Dependency freshness reporting | Staleness visible (report-only v1) | npm/uv outdated | 2–3 Nice |
| Artifact / install weight | Pack/install footprint signal (informational) | `npm pack --dry-run` / wheel size | 3 Nice |

**Python Ruff scope (task-006):** `src/avo/`, `tests/`, and `helpers/` share the same Ruff rule set (`pyproject.toml` `[tool.ruff]`). Coverage remains `--cov=avo` (helpers shims are linted, not coverage-primary). Prefer new code under `src/avo/`.

### Measured inputs and execution captures

The gate table retains all nine fast gates plus light mutation. PASS/FAIL labels
and policy limits are decisions, not metric values. The measurements table shows
observed numbers with scope, input counts, artifact references, and hashes;
missing or incomplete observations stay unavailable or partial. Configured
allowlist/contract counts remain configuration diagnostics.

`run_quality_gate.py` wraps the CI commands without changing their failure
behavior. Each `reports/quality/gates/<gate>/gate.json` binds the exact command,
SHA/run, UTC time/duration, exit outcome or signal, source fingerprints, log hash,
and produced-file hashes to `gate.log` (combined stdout/stderr). The publisher
revalidates downloaded receipts and files from that run. Missing, stale,
modified, or malformed output cannot masquerade as a successful zero; an
unavailable measurement can coexist with a recorded command outcome.

| Measured input | Contents and limits |
| --- | --- |
| `complexity.json` | Actual block locations, scores/ranks, matched exception reasons/ceilings, unwaived/worsened findings, stale entries, and errors; configured exception count is separate |
| `deadcode.json` | Actual Vulture locations/kinds/confidence, matched reasons, unwaived findings, stale entries, and errors; scan failure is incomplete, not zero findings |
| `pip-audit-raw.json` / `npm-audit-raw.json` | Sanitized tool JSON retaining advisory descriptions/fix versions and dependency paths, command/provenance, and exact audit policy; absent scans are explicit |
| `deps-findings.json` / `npm-audit-summary.json` | Blocking findings and npm severity totals; all unignored Python advisories block, npm criticals block, and high/moderate/low remain reported |
| `coverage.json` / `jscpd-report.json` | Actual covered/executable and duplicated/total line counts with clone pairs, under existing 68%/2% policies |
| `dependency-tree.json` | Proposed add/remove/change counts from npm's dry run; proposals are not applied and remain report-only |
| `code-risk.json` | Per-function identity/source line, cyclomatic complexity, statement coverage, CRAP inputs/results, and static package CA/CE counts |

Unit and integration lanes capture `unit-tests.xml` / `integration-tests.xml`
through `PYTEST_ADDOPTS` and publish separate `unit-test-evidence` /
`integration-test-evidence` artifacts containing XML, receipts, and logs.
`test_execution_evidence.py` counts actual testcase events (passed, failed,
errors, skipped), independently of job status. Failed/interrupted runs can retain
partial counts; missing or invalid XML provides no count. These observations
do not imply a safe-fix or repair-success percentage. Artifact URLs identify the
current upload, and local run identifiers designate local previews.

### Informational CRAP and package coupling

Function/method CRAP is `CC² × (1 − covered statements / statements)³ + CC`.
It uses the function's own statement counts, including when coverage has branch
instrumentation. The raw coverage hash, SHA/run, successful coverage execution,
and unchanged source fingerprints must agree. File/repository averages do not
substitute for function coverage. Ambiguous, unmatched, excluded, or
zero-statement functions remain unmeasured. The report labels its maximum
**max observed** and includes measured/unmeasured counts plus exact location
inputs. Reference 30 is a review aid, not a new gate; existing complexity
ceilings and coverage floors stay authoritative.

Package CA counts distinct incoming packages; CE counts distinct outgoing
packages. Aggregation is `avo.<package>`, using the repaired static internal
import graph. Instability is `CE / (CA + CE)` and is undefined without edges.
Within-package and dynamic imports are outside scope. These observations
identify review candidates, without proving god classes or introducing
abstractness, main-sequence distance, or quadrant policy.

### npm quality scripts (task-003)

| Script | Role |
| --- | --- |
| `quality` | Umbrella for Phase 1 fast gates |
| `quality:lint` | Ruff + ESLint |
| `quality:format` | Ruff format check + Prettier check |
| `test:coverage` | pytest-cov uses the authoritative `[tool.coverage.report] fail_under = 68` |
| `quality:deps` | pip-audit `--skip-editable` + npm critical (`check_npm_audit.py`; allowlist `deps-audit-allowlist.json`; high, moderate, and low reported) |
| `quality:complexity` | xenon max-absolute **B** via `scripts/ci/check_complexity.py` + `complexity-allowlist.json` (C901 ≤ 31 also enforced in `quality:lint`) |
| `quality:deadcode` | vulture via `check_deadcode.py` (min_confidence **60** + `deadcode-allowlist.json`) |
| `quality:duplication` | jscpd on `src/avo` (threshold **2%** via `.jscpd.json`; fail-immediately) |
| `quality:architecture` | import-linter via `.importlinter` (`quality-architecture.sh`; fail-immediately) |
| `quality:mutation` | mutmut via `quality-mutation.sh` (full profile; `check_mutation.py` floor) |
| `quality:tree` | npm find-dupes dry-run (`quality-tree.sh`; command failure fails; hoist plan report-only) |
| `quality:dep-graph` | Self-contained `src/avo` dependency table + DOT export (`run-dep-graph.sh` / `avo_dep_graph.py`); isolated packages included, invalid source fails visibly |

### Quality in CI (task-005 / task-008 / spec v1.4)

| Workflow | Trigger | Role |
| --- | --- | --- |
| `ci.yml` | PR / push | Standard blocking Software quality gates, parallel unit/runtime integration, light mutation, Gate 2, and always-run **CI readiness**. The final **Quality report** job combines current-run artifacts into one dashboard/comment and release evidence; missing images preserve tables. Unit uses frozen dev dependencies; quality and integration additionally install MCP. See [quality reporting](quality-reporting.md). |
| `mutation-full.yml` | Weekly + `workflow_dispatch` | Full critical-file mutation (**20-minute** timeout); artifacts 14d; floor **50%** (`mutation-config.json`) |
| `size-signal.yml` | PR (`feature/*`→`develop`, `develop`→`release`) | Informational pack/install weight sticky comment (non-blocking) |
| `dependency-graph.yml` | Weekly + `workflow_dispatch` | HTML dependency table + DOT export (14d), with SHA/UTC/scope; not on PR fast path |
| `watch-skill-smoke.yml` | Weekly + `workflow_dispatch` | watch-skill runtime invoke + diagnostics on failure (7d) |
| `quality-toolchain-smoke.yml` | Weekly + `workflow_dispatch` | ruff/xenon/vulture/pip-audit/lint-imports/mutmut/jscpd `--version`/`--help` |

Software quality lives in `ci.yml` (no separate Gate 3 workflow file). Phase-1 Must
Have gates are hard gates under job **`Software quality`** (task-013 — require that
check name in branch protection). HyperFrames exemplar lint stays a **domain** gate
(`hf:lint`), not language lint.

---

## Test runner

| Command | Purpose |
| --- | --- |
| `uv sync --frozen --extra dev --extra mcp` | Locked install for quality/integration CI + local quality tools (unit CI needs only dev) |
| `npm run test:unit` | **AVO core units** — ignore `tests/projects` and `tests/integration` |
| `npm run test:integration` | Runtime/subprocess tests under `tests/integration` |
| `npm run test:projects` | Footage-project / spec-scoped tests only |
| `pytest` | Everything (core + projects) |
| `bash scripts/ci/run-unit-tests.sh` | Canonical CI entry (core only; needs frozen sync on PATH) |

**Enforcement:** `tests/test_quality_matrix.py` fails if workflows or docs drift.

Provider instances (e.g. `providers/bishop/`) are **gitignored** and never required for core tests.

---

## Test matrix

### Tier A — Orchestrator (always in PR CI)

| Test module | Covers |
| --- | --- |
| `test_avo_config` | `avo.config.json`, validate helper smoke |
| `test_avo_commands` | Command parity |
| `test_install_scripts` | Install slug `joaobispo2077/avo` |
| `test_validate_dependencies` | Gate 1 manifest |
| `test_local_only_customization` | Local-only paths |
| `test_workflow_compatibility` | Workflow contracts |
| `test_gitignore_scope` | Provider gitignore |
| `test_video_use_traces` | Product identity |
| `test_software_foundation` | Foundation file layout |
| `test_quality_matrix` | Doc/workflow drift guard |
| `test_deadcode_gate` | Vulture dead-code gate + allowlist contract |
| `test_gate_evidence` | Command outcomes, receipt identity, raw logs, hashes, and signals |
| `test_quality_measurements` | Measured inputs and their separation from gate/configuration values |
| `test_test_execution_evidence` | Native JUnit events, partial captures, and unavailable evidence |
| `test_code_risk_metrics` | Function coverage/CRAP provenance and static package coupling |
| `test_init_project` | `src/avo/init_project.py` scaffold |

### Tier B — Engine core (AVO core pytest, PR CI)

| Test module | Covers |
| --- | --- |
| `test_transcribe` | `src/avo/transcribe.py` (mocked Whisper) |
| `test_transcribe_batch` | Batch transcribe |
| `test_transcribe_cache` | Cache invalidation |
| `test_prepare_transcription` | Model prep (mocked download) |
| `test_transcript_contract` | Transcript schema |
| `test_edl_v3_contract` | EDL v3 + `validate_edl.py` |
| `test_caption_plan` | Caption planning |
| `test_render_schema_selection` | Render schema (generic) |
| `test_overlay_composite` | Overlay composite |
| `test_audio_sfx_pipeline` | Audio SFX pipeline |

### Tier C — Footage projects (local only, **not** PR CI)

Under `tests/projects/` — `@pytest.mark.project`. Spec-scoped edits only.
Run: `npm run test:projects`.

| Test module | Spec / project |
| --- | --- |
| `projects/test_switch_comparison_edl_contract.py` | `003-switch-comparison-video` |
| `projects/test_switch_comparison_motion_briefs.py` | `003-switch-comparison-video` |
| `projects/test_final_transcript_artifacts.py` | switch-comparison exports |
| `projects/test_bluray_ps5_edl_contract.py` | `005-bluray-ps5-gamevlog` |
| `projects/test_bluray_ps5_render_schema.py` | `005-bluray-ps5-gamevlog` |

### Tier D — Slow / manual workflows

| Workflow | Extra checks |
| --- | --- |
| `orchestrator-smoke.yml` | Whisper tiny model, optional tools, AVO core pytest |
| `setup-smoke.yml` | Full setup ubuntu/windows |
| `ffmpeg-whisper-smoke.yml` | Binary import smoke |
| `watch-skill-smoke.yml` | watch-skill clone + invoke |
| `quality-toolchain-smoke.yml` | Quality/mutation CLI versions |

---

## Workflow trigger matrix

| Workflow | Trigger | Tests |
| --- | --- | --- |
| `ci.yml` | PR + push main/develop/feature | AVO core pytest + software quality job + light mutation |
| `mutation-full.yml` | weekly + `workflow_dispatch` | mutmut on critical files (full floor, 20-minute timeout) |
| `size-signal.yml` | PR (informational) | Pack / install footprint signal |
| `dependency-graph.yml` | weekly + `workflow_dispatch` | Optional HTML package dependency table + DOT export |
| `watch-skill-smoke.yml` | weekly + `workflow_dispatch` | watch-skill runtime smoke |
| `quality-toolchain-smoke.yml` | weekly + `workflow_dispatch` | Quality/mutation CLI smokes |
| `release.yml` | `v*` tags | AVO core pytest + version check + GitHub Release |
| `orchestrator-smoke.yml` | weekly + manual | AVO core pytest + model prep |
| `setup-smoke.yml` | manual | Setup scripts |
| `ffmpeg-whisper-smoke.yml` | manual | ffmpeg/whisper imports |

---

## Known gaps (deferred)

| Helper | Status |
| --- | --- |
| `helpers/grade.py` | No dedicated unit test — manual QC |
| `src/avo/telemetry.py` | No dedicated unit test |
| `src/avo/hardware.py` | No dedicated unit test |
| `helpers/validate_edl.py` CLI | Covered indirectly via EDL contract tests |

---

## Local quality checklist

```bash
uv sync --frozen --extra dev --extra mcp
npm ci
bash scripts/validate-prerequisites.sh --ci
bash scripts/ci/run-unit-tests.sh          # AVO core only
bash scripts/validate-usability.sh --ci
npm run test:unit

# Software quality (ci.yml job `Software quality` — Phase-1 blocking):
npm run quality:lint
npm run quality:format
npm run test:coverage   # authoritative fail_under 68 in pyproject
npm run quality:complexity
npm run quality:deps
npm run quality:deadcode   # vulture min_confidence 60 + deadcode-allowlist.json
npm run quality:duplication
npm run quality:architecture
npm run quality:tree
# or full umbrella:
npm run quality
# Slow / local extras:
npm run quality:mutation     # Ubuntu-oriented; full mutmut
npm run quality:dep-graph    # writes reports/dep-graph

# Optional — footage-project tests (not gated in CI):
npm run test:projects
```

Pre-tag (maintainer):

```bash
bash scripts/ci/verify-release-version.sh v0.1.0   # after CHANGELOG section exists
```

---

*Maintained as part of the software quality refactor.*
