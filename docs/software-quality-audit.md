# AVO Software Quality Audit

**Task:** `avo-refactoring-software-quality` · **Date:** 2026-08-01

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

**CI order (`ci.yml`):** Gate 1 → software quality ∥ pytest **AVO core** (`-m "not project"`) + install smoke + hf:doctor → Gate 2.

**Release order:** Gate 1 → Gate 2 → pytest (AVO core) → version check → GitHub Release.

Gate 1/2 behavior is unchanged. Software quality is **standard CI**, not a separate workflow.

---

## Software quality concepts (stub)

Concept-first dashboard: tools may swap; concepts and fail/pass criteria are the product.
Local umbrella: `npm run quality` (Phase 1 fast gates). Drift lock: `tests/test_quality_matrix.py`.

| Concept | What it proves | Current tool (plan) | Phase |
| --- | --- | --- | --- |
| Static lint / format | Machine-consistent Python + JS surface | Ruff; ESLint + Prettier + EditorConfig | 1 Must |
| Type safety | Contracts at boundaries (lint now; mypy ratchet later) | typescript-eslint; mypy phased | 1–2 |
| Test coverage floor | Product paths exercised under fail-under **68%** (line; baseline 2026-08-14, floor of ~68.5%) | pytest-cov (`src/avo`; `branch = false`) | 1 Must |
| Complexity | No god-functions above max-absolute B (allowlisted debt documented); C901 ≤ 31 | xenon via `check_complexity.py` + allowlist; Ruff C901 (`max-complexity = 31`) in lint | 1 Must |
| Dependency security audit | High+ vulns fail | pip-audit; `npm audit` high+ via `check_npm_audit.py` + `deps-audit-allowlist.json`; `@semantic-release/npm` file stub (`scripts/ci/semantic-release-npm-stub`) avoids nested vulnerable npm CLI bundles | 1 Must |
| Lock / install reproducibility | Frozen installs in quality/unit CI | `uv sync --frozen`; `npm ci` | 1 Must |
| Dependency tree health | Unexpected npm dupes / lock drift visible (`npm find-dupes` dry-run; command failure fails CI; non-empty hoist plan is report-only until `/evolve`) | `quality:tree` / `quality-tree.sh` (`npm find-dupes`); uv lock | 2 Should |
| Dead code | No unused weight outside allowlist | vulture (`check_deadcode.py`, min_confidence **60** + `deadcode-allowlist.json`) | 2 Should |
| Duplication | AI copy-paste blocked over threshold (**2%**; baseline ~1.09% lines 2026-08-14) | jscpd (`.jscpd.json` + `quality-duplication.sh`) | 2 Should |
| Architecture / import boundaries | Forbidden imports fail (layer map + grandfathered CLI/render/shorts/timeline→adapter edges) | import-linter (`.importlinter` + `quality-architecture.sh`); `helpers/` shims are outside `root_package = avo` | 2 Should |
| Visual dependency graph | Weekly picture of `src/avo` coupling (non-blocking for PRs) | `dependency-graph.yml` + `quality:dep-graph` / `avo_dep_graph.py` (HTML+DOT artifact, 14d) | 3 Should |
| Mutation testing | Tests catch wrong behavior — **light/PR** + **full/weekly** | mutmut Ubuntu; **20-minute** job timeout on light and full; light mutates a small explicit file set; full mutates the rest of the critical set except `cli_tools.py`; floors 40% / 50% (`mutation-config.json`); per-mutant `timeout_multiplier = 3.0` | 3 Must |
| Dependency freshness reporting | Staleness visible (report-only v1) | npm/uv outdated | 2–3 Nice |
| Artifact / install weight | Pack/install footprint signal (informational) | `npm pack --dry-run` / wheel size | 3 Nice |

**Python Ruff scope (task-006):** `src/avo/`, `tests/`, and `helpers/` share the same Ruff rule set (`pyproject.toml` `[tool.ruff]`). Coverage remains `--cov=avo` (helpers shims are linted, not coverage-primary). Prefer new code under `src/avo/`.

### npm quality scripts (task-003)

| Script | Role |
| --- | --- |
| `quality` | Umbrella for Phase 1 fast gates |
| `quality:lint` | Ruff + ESLint |
| `quality:format` | Ruff format check + Prettier check |
| `test:coverage` | pytest-cov `--cov-fail-under=68` (baseline floor; also `[tool.coverage.report]`) |
| `quality:deps` | pip-audit `--skip-editable` + npm high+ (`check_npm_audit.py`; allowlist `deps-audit-allowlist.json`) |
| `quality:complexity` | xenon max-absolute **B** via `scripts/ci/check_complexity.py` + `complexity-allowlist.json` (C901 ≤ 31 also enforced in `quality:lint`) |
| `quality:deadcode` | vulture via `check_deadcode.py` (min_confidence **60** + `deadcode-allowlist.json`) |
| `quality:duplication` | jscpd on `src/avo` (threshold **2%** via `.jscpd.json`; fail-immediately) |
| `quality:architecture` | import-linter via `.importlinter` (`quality-architecture.sh`; fail-immediately) |
| `quality:mutation` | mutmut via `quality-mutation.sh` (full profile; `check_mutation.py` floor) |
| `quality:tree` | npm find-dupes dry-run (`quality-tree.sh`; command failure fails; hoist plan report-only) |
| `quality:dep-graph` | Visual `src/avo` import graph (`run-dep-graph.sh` / `avo_dep_graph.py`) |

### Quality in CI (task-005 / task-008 / spec v1.4)

| Workflow | Trigger | Role |
| --- | --- | --- |
| `ci.yml` | PR / push | Standard CI **Software quality** job (**blocking** Phase-1 umbrella; branch-protection check name **`Software quality`**): lint + format **fail-immediately** (includes Ruff C901 ≤ 31), coverage fail-under via `run-coverage.sh` (floor **68%**), complexity via `quality-complexity.sh` (xenon max-absolute **B** + allowlist), deps via `quality-deps.sh` (`pip-audit` + npm high+ via `check_npm_audit.py`, **fail-immediately**; documented GHSA exceptions in `deps-audit-allowlist.json`), deadcode via `quality-deadcode.sh` (vulture min_confidence **60** + `deadcode-allowlist.json`), duplication via `quality-duplication.sh` (jscpd `.jscpd.json` threshold **2%**, baseline ~1.09%), architecture via `quality-architecture.sh` (import-linter `.importlinter`), tree health via `quality-tree.sh` (`npm find-dupes` dry-run). On pull requests the job posts a **sticky Software quality table** (one comment, section per gate). Gate 2 `needs` this job. Unit + quality jobs install via `uv sync --frozen --extra dev`. Node **24**; GitHub-owned actions on Node 24 majors. |
| `mutation-full.yml` | Weekly + `workflow_dispatch` | Full critical-file mutation (**20-minute** timeout); artifacts 14d; floor **50%** (`mutation-config.json`) |
| `size-signal.yml` | PR (`feature/*`→`develop`, `develop`→`release`) | Informational pack/install weight sticky comment (non-blocking) |
| `dependency-graph.yml` | Weekly + `workflow_dispatch` | Visual `src/avo` import graph artifact (14d); not on PR fast path |
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
| `uv sync --frozen --extra dev` | Locked install for quality/unit CI + local quality tools |
| `npm run test:unit` | **AVO core** — `pytest -m "not project"` |
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
| `dependency-graph.yml` | weekly + `workflow_dispatch` | Visual src/avo import graph |
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
uv sync --frozen --extra dev
npm ci
bash scripts/validate-prerequisites.sh --ci
bash scripts/ci/run-unit-tests.sh          # AVO core only
bash scripts/validate-usability.sh --ci
npm run test:unit

# Software quality (ci.yml job `Software quality` — Phase-1 blocking):
npm run quality:lint
npm run quality:format
npm run test:coverage   # fail_under 68 (pyproject + --cov-fail-under)
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
