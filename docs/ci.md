# AVO CI/CD (agent-facing)

Dense reference for the GitHub Actions pipeline and local gate commands. User-facing
summary: README **Built on** section only; this doc is for agents and maintainers.

## Standard CI validation model (+ software quality)

AVO is an **orchestrator**. CI must validate **external toolchain prerequisites**
before asserting the repo itself is usable. **Software quality** (lint, coverage,
complexity, audits, …) is part of the **standard `ci.yml` pipeline** — not a
separate workflow. Local umbrella: `npm run quality`. See
[software-quality-audit.md](./software-quality-audit.md).

| Lane | Script / job | What it checks |
| --- | --- | --- |
| **Gate 1** | `scripts/validate-prerequisites.sh --ci` | GitHub Spec Kit (`.specify`), video-use engine, ffmpeg (warn in CI), watch-skill, HyperFrames, optional clones — see `avo.dependencies.json` |
| **Unit tests** | `scripts/ci/run-unit-tests.sh` | AVO core pytest; Python via `uv sync --frozen --extra dev` |
| **Software quality** | `quality-lint.sh` + `quality-format.sh` + `run-coverage.sh` + `quality-complexity.sh` + `quality-deps.sh` + `quality-deadcode.sh` + `quality-duplication.sh` + `quality-architecture.sh` + `quality-tree.sh` (job `Software quality` in `ci.yml`) | Lint/format **fail-immediately** (Ruff C901 ≤ **31**); coverage fail-under **68%**; complexity xenon max-absolute **B** + `complexity-allowlist.json`; deps **fail-immediately** (`pip-audit` + npm high+ via `check_npm_audit.py` / `deps-audit-allowlist.json`); deadcode vulture min_confidence **60** + `deadcode-allowlist.json`; duplication jscpd threshold **2%** (`.jscpd.json`); architecture import-linter `.importlinter`; tree health `npm find-dupes` (command failure fails; hoist plan report-only). Python via `uv sync --frozen --extra dev`. Local: `npm run quality:*` / `test:coverage` |
| **Gate 2** | `scripts/validate-usability.sh --ci` | `avo.config.json`, provider scaffolds, `setup.sh --dry-run`, scaffold scripts — after Gate 1 + unit tests + software quality |

Order in `.github/workflows/ci.yml` is enforced via job `needs:`.

### Branch protection — required checks (task-013)

On `main` / `release` (and any PR target that uses this workflow), require these
**exact** GitHub Actions check names (job `name:` fields from `ci.yml`):

| Required check name | Job id | Role |
| --- | --- | --- |
| `Gate 1 — Orchestrator prerequisites` | `prerequisites-gate` | Toolchain prerequisites |
| `Unit tests (AVO repo)` | `repo-unit-tests` | AVO core pytest + install/hf smokes |
| `Software quality` | `software-quality` | **Phase-1 fast gates** (lint, format, coverage, complexity, deps) + deadcode, duplication, architecture, tree — fail-immediately |
| `Mutation tests (light)` | `mutation-light` | Scoped mutmut after unit tests; fails below `mutation-config.json` light floor (Ubuntu) |
| `Gate 2 — Project usability` | `usability-gate` | Project usability; `needs` includes `software-quality` |

Do **not** require a separate Gate 3 / quality workflow check — software quality is
the `Software quality` job inside workflow **CI**.

### Related workflows (expected paths)

| Workflow | Role |
| --- | --- |
| `ci.yml` | Standard CI: Gate 1 → unit tests ∥ software quality → Gate 2; light mutation job after unit tests |
| `mutation-full.yml` | Weekly + dispatch full mutation (slow lane) |
| `size-signal.yml` | Informational PR size/weight signal (non-blocking) |
| `dependency-graph.yml` | Weekly visual `src/avo` import graph artifact |
| `watch-skill-smoke.yml` | Manual/weekly watch-skill invoke (beyond Gate 1 clone) |
| `quality-toolchain-smoke.yml` | Manual/weekly ruff/xenon/mutmut/jscpd CLI smokes |

Drift lock: `tests/test_quality_matrix.py` asserts npm quality script names,
`ci.yml` quality job + hard lint/format/coverage/complexity/deps steps, coverage
fail-under 68, `uv sync --frozen --extra dev` on quality/unit jobs, Phase-1
blocking posture (`usability-gate` `needs` `software-quality` + required check
name **`Software quality`**), no separate Gate 3 workflow file, and slow-lane
workflow basenames.

## Manifests

| File | Role |
| --- | --- |
| `config/avo.config.json` | Job routing (which tool owns which stage) |
| `config/avo.dependencies.json` | Gate 1 — pinned repos, clone paths, required vs optional |

Every `job` in `config/avo.dependencies.json` must exist under `config/avo.config.json` → `jobs`.

## Release automation

- Config: [`release.config.mjs`](../release.config.mjs) (semantic-release plugins)
- Workflow: `.github/workflows/release.yml` runs after **CI** succeeds on `develop` (alpha) or `release` (stable)
- Secret: `GH_TOKEN` with `contents: write` (see [versioning.md](./versioning.md))

## Workflows (maxframe-style layout)

| Workflow | Trigger | Purpose |
| --- | --- | --- |
| `ci.yml` | PR + push to `main`, `release`, `develop`, `feature/**` | Gate 1 → unit tests + `hf:doctor` ∥ software quality → Gate 2; light mutation |
| `mutation-full.yml` | weekly + `workflow_dispatch` | Full critical-package mutation (mutmut); artifacts |
| `size-signal.yml` | PR | Informational pack/install footprint (non-blocking) |
| `dependency-graph.yml` | weekly + `workflow_dispatch` | Visual `src/avo` import graph (`quality:dep-graph`) |
| `watch-skill-smoke.yml` | weekly + `workflow_dispatch` | watch-skill clone + CLI/help invoke |
| `quality-toolchain-smoke.yml` | weekly + `workflow_dispatch` | ruff, xenon, vulture, pip-audit, lint-imports, mutmut, jscpd |
| `setup-smoke.yml` | `workflow_dispatch` | Full `setup.sh` on ubuntu + windows |
| `orchestrator-smoke.yml` | manual + weekly cron | Gate 1 (+ optional) + Whisper tiny model + Gate 2 |
| `ffmpeg-whisper-smoke.yml` | `workflow_dispatch` | Binary/import smoke (like maxframe `yt-dlp-smoke.yml`) |
| `release.yml` | After **CI** on `develop` / `release` (+ manual) | semantic-release dry-run → publish (alpha on `develop`, stable on `release`) |

Reference: [maxframe workflows](https://github.com/joaobispo2077/maxframe/tree/main/.github/workflows).

## Local reproduce

```bash
npm ci
# Quality/unit CI path (locked — matches ci.yml repo-unit-tests + software-quality):
uv sync --frozen --extra dev
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

## Branch protection (block merge until CI passes)

`main` and `release` should require these **CI** job checks before merge. GitHub
shows them under the commit/PR checks tab with these exact names:

- `Gate 1 — Orchestrator prerequisites`
- `Unit tests (AVO repo)`
- `Software quality`
- `Mutation tests (light)`
- `Gate 2 — Project usability`

### GitHub UI

1. **Settings → Rules → Rulesets → New branch ruleset**
2. **Target branches:** `main`, `release`
3. Enable **Require status checks to pass**
4. Search and add the **five** job names above (pick the GitHub Actions ones), including **`Software quality`** and **`Mutation tests (light)`**
5. Enable **Require branches to be up to date before merging** (recommended)
6. Save — set enforcement to **Active**

Repo already has ruleset `no-delete-no-force` on `main` (blocks delete/force-push only).
Add a separate ruleset or extend targets; do not rely on that ruleset for CI gating.

### `gh` CLI (repository ruleset)

Run from a machine with admin access to `joaobispo2077/avo`:

```bash
gh api repos/joaobispo2077/avo/rulesets -X POST -f name="require-ci" -f target=branch -f enforcement=active -f bypass_actors='[]' -F 'conditions={"ref_name":{"include":["refs/heads/main","refs/heads/release"],"exclude":[]}}' -F 'rules=[{"type":"pull_request","parameters":{"required_approving_review_count":0,"dismiss_stale_reviews_on_push":false,"require_code_owner_review":false,"require_last_push_approval":false,"required_review_thread_resolution":false}},{"type":"required_status_checks","parameters":{"strict_required_status_checks_policy":true,"required_status_checks":[{"context":"Gate 1 — Orchestrator prerequisites"},{"context":"Unit tests (AVO repo)"},{"context":"Software quality"},{"context":"Mutation tests (light)"},{"context":"Gate 2 — Project usability"}]}}]'
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
