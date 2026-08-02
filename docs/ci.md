# AVO CI/CD (agent-facing)

Dense reference for the GitHub Actions pipeline and local gate commands. User-facing
summary: README **Built on** section only; this doc is for agents and maintainers.

## Two-gate validation model

AVO is an **orchestrator**. CI must validate **external toolchain prerequisites**
before asserting the repo itself is usable.

| Gate | Script | What it checks |
| --- | --- | --- |
| **Gate 1** | `scripts/validate-prerequisites.sh --ci` | GitHub Spec Kit (`.specify`), video-use engine, ffmpeg (warn in CI), watch-skill, HyperFrames, optional clones — see `avo.dependencies.json` |
| **Gate 2** | `scripts/validate-usability.sh --ci` | `avo.config.json`, provider scaffolds, `setup.sh --dry-run`, scaffold scripts — **only after Gate 1** |

Gate order in CI is enforced via job `needs:` in `.github/workflows/ci.yml`.

## Manifests

| File | Role |
| --- | --- |
| `config/avo.config.json` | Job routing (which tool owns which stage) |
| `config/avo.dependencies.json` | Gate 1 — pinned repos, clone paths, required vs optional |

Every `job` in `config/avo.dependencies.json` must exist under `config/avo.config.json` → `jobs`.

## Release automation

- Config: [`release.config.mjs`](../release.config.mjs) (semantic-release plugins)
- Workflow: `.github/workflows/release.yml` — runs after **CI** succeeds on `dev` (alpha) or `main` (stable)
- Secret: `GH_TOKEN` with `contents: write` (see [versioning.md](./versioning.md))

## Workflows (maxframe-style layout)

| Workflow | Trigger | Purpose |
| --- | --- | --- |
| `ci.yml` | PR + push to `main` | Gate 1 → unit tests + `hf:doctor` → Gate 2 |
| `setup-smoke.yml` | `workflow_dispatch` | Full `setup.sh` on ubuntu + windows |
| `orchestrator-smoke.yml` | manual + weekly cron | Gate 1 (+ optional) + Whisper tiny model + Gate 2 |
| `ffmpeg-whisper-smoke.yml` | `workflow_dispatch` | Binary/import smoke (like maxframe `yt-dlp-smoke.yml`) |
| `release.yml` | After **CI** on `dev` / `main` (+ manual) | semantic-release dry-run → publish (alpha on `dev`, stable on `main`) |

Reference: [maxframe workflows](https://github.com/joaobispo2077/maxframe/tree/main/.github/workflows).

## Local reproduce

```bash
npm ci
pip install -e .

# Gate 1 (orchestrator prerequisites)
npm run validate:prerequisites -- --ci
# or: bash scripts/validate-prerequisites.sh --ci

# Gate 2 (project usability — run after Gate 1 passes)
npm run validate:usability -- --ci

# CI unit tests (full suite)
pip install -e ".[dev]"
bash scripts/ci/run-unit-tests.sh
# or: pytest
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

## Adding a new orchestrated dependency

1. Add job to `avo.config.json` if new stage.
2. Add tool entry to `avo.dependencies.json` (repo URL, clone path, `required`).
3. Extend `src/avo/validate_dependencies.py` if new `kind` is needed.
4. Update `install.md` setup order if setup.sh prepares it.
