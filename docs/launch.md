# AVO GitHub launch checklist

Pre-push verification for publishing the orchestrator repo at **`joaobispo2077/avo`**
(`https://github.com/joaobispo2077/avo`).

---

## Repository hygiene

- [ ] `.gitignore` covers skills trees (`.agents/`, `.claude/`), SDD dev (`.cursor/`, `.sdd/`), scratch (`compositions/`, `assets/`), tool clones, `specs/`, `models/`
- [ ] Legacy fork files removed from git: `skills/manim-video/`, `poster.html`, `static/video-use-banner.png`
- [ ] No secrets staged (`.env`, keys, `.ai-memory.toml`)
- [ ] `docs/repo-layout.md` matches actual tree

## Orchestrator core staged

- [ ] `helpers/`, `scripts/`, `docs/`, `tests/`, `providers/`, `static/avo*`, `.github/`, `.specify/`
- [ ] `avo.config.json`, `avo.dependencies.json`, manifests
- [ ] `README.md`, `install.md`, `AGENTS.md`, `LICENSE`

## Install slug QA

- [ ] Default install slug is **`joaobispo2077/avo`** in `bin/install.cjs`, `install.sh`, `install.ps1`, `skills.json`, `install.md` (Tier 1), README install block
- [ ] **`browser-use/video-use`** appears only where crediting the upstream editing engine (README fork line, routing table, Built on)
- [ ] `pytest tests/test_install_scripts.py -v` passes (includes default REPO assertion)

## Gitignore scope QA

- [ ] Personal providers ignored: `git check-ignore -v providers/bishop/avo.provider.json` (or any real slug)
- [ ] Scaffold still trackable: `git check-ignore providers/_template/avo.provider.json` → exit 1 (not ignored)
- [ ] Only `providers/_template/`, `providers/avo.provider.schema.json`, `providers/README.md` ship — no personal `H:/…` paths in staged files
- [ ] `pytest tests/test_gitignore_scope.py -v` passes
- [ ] `python helpers/validate_usability.py` passes without a personal provider present

## Engine vs product identity QA

- [ ] Constitution title is **AVO** (`.specify/memory/constitution.md`)
- [ ] `package-lock.json` name matches `package.json` (`avo`)
- [ ] Workflow SVG labels **AVO engine**, not "Video Use"
- [ ] **`video-use`** in tracked files is engine routing or upstream credit only — see [engine-vs-orchestrator.md](engine-vs-orchestrator.md)
- [ ] `pytest tests/test_software_foundation.py tests/test_quality_matrix.py -v` passes

## Software foundation QA

- [ ] `CHANGELOG.md` present with SemVer note
- [ ] `docs/versioning.md`, `docs/branching.md`, `docs/software-foundation.md` present
- [ ] Cursor rules: `.cursor/rules/00-core-behavior.mdc` … `50-documentation-policy.mdc`
- [ ] Copilot: `.github/instructions/testing.instructions.md`, `design-principles.instructions.md`, `versioning-and-documentation.instructions.md`
- [ ] Skills: `.claude/skills/design-pattern-selection`, `architecture-selection` (+ `.cursor/skills/` mirror)
- [ ] `docs/software-quality-audit.md` present; `pytest tests/test_quality_matrix.py -v` passes
- [ ] `AGENTS.md` § Software Engineering Foundation present

## Brand

- [ ] README title: `# AVO` (subtitle on banner / tagline only)
- [ ] `static/avo/banner.svg` + `static/avo-banner.png` aligned and current
- [ ] No stale **product** identity in constitution, package-lock, or workflow SVG (upstream engine credits OK — see [engine-vs-orchestrator.md](engine-vs-orchestrator.md))

## Validation (run locally)

```bash
python helpers/validate_dependencies.py          # Gate 1
python helpers/validate_usability.py
pip install -e ".[dev]"
bash scripts/ci/run-unit-tests.sh
```

## Fresh-clone smoke (recommended)

```bash
git clone https://github.com/joaobispo2077/avo.git /tmp/avo-smoke && cd /tmp/avo-smoke
bash scripts/setup.sh --lang en --dry-run
python helpers/validate_dependencies.py
```

## First push (human-only — agents must NOT run this)

When the checklist above passes, the **maintainer** publishes the repo:

```bash
git init
git add .
git commit -m "first commit"
git branch -M main
git remote add origin https://github.com/joaobispo2077/avo.git
git push -u origin main
```

If `origin` already points at a fork (e.g. `browser-use/video-use`), update it first:

```bash
git remote set-url origin https://github.com/joaobispo2077/avo.git
git push -u origin main
```

After push, verify raw install URLs resolve:

```bash
curl -fsSL https://raw.githubusercontent.com/joaobispo2077/avo/main/install.sh | head
```

## Human sign-off

- [ ] README use cases and Quickstart read cleanly for a new user
- [ ] README **Supported agents** section present
- [ ] CI workflows present under `.github/workflows/`
- [ ] Remote URL and repo description set on GitHub
- [ ] **Push approved by maintainer**

---

See [`repo-layout.md`](repo-layout.md) for what ships vs install-time.
