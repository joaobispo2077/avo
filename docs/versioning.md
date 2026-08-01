# Versioning — AVO orchestrator

AVO uses **two versioning systems** for different artifacts.

---

## 1. Software releases (this repo) — SemVer

| Item | Convention |
| ---- | ---------- |
| Version | `MAJOR.MINOR.PATCH` (e.g. `0.2.0`) |
| Git tag | `vMAJOR.MINOR.PATCH` annotated tag |
| Changelog | `CHANGELOG.md` at repo root |
| Package | `pyproject.toml` / `package.json` `version` field |

### Bump rules

- **MAJOR** — breaking API/CLI/config changes for integrators
- **MINOR** — backward-compatible features
- **PATCH** — backward-compatible fixes, safe doc corrections tied to a release

### When agents update `CHANGELOG.md`

Only after the user clearly signals the task is **100% finished and working**
(e.g. "approved", "task finished", "we can release/tag it").

The agent must:

1. Read existing `CHANGELOG.md` and tags (`git tag -l 'v*'`)
2. Choose the next SemVer version
3. Move `[Unreleased]` items into a dated version section
4. Reference ticket or scope (see [branching.md](./branching.md))
5. **Recommend** tag commands — do **not** run them unless explicitly asked

```bash
git tag -a v0.2.0 <commit-sha> -m "v0.2.0"
git push origin v0.2.0
```

### Pre-release tags (optional)

- Alpha: `v1.0.0-alpha.1`
- Immutable once published — never move or rewrite tags on the remote

### Release workflow (orchestrator)

On push of annotated tag `vX.Y.Z`:

1. CI `release.yml` runs Gate 1, Gate 2, and full pytest
2. `scripts/ci/verify-release-version.sh` confirms tag matches `package.json`,
   `pyproject.toml`, and `CHANGELOG.md` section `## [X.Y.Z]`
3. GitHub Release is created with notes from `scripts/ci/extract-changelog-section.sh`

**Pre-tag checklist (maintainer):**

```bash
pip install -e ".[dev]"
pytest
bash scripts/ci/verify-release-version.sh v0.1.0   # after CHANGELOG section exists
git tag -a v0.1.0 <commit-sha> -m "v0.1.0"
git push origin v0.1.0
```

See [software-quality-audit.md](./software-quality-audit.md) and [ci.md](./ci.md).

---

## 2. Video export versions (footage projects) — editorial

For work under `<footage>/edit/`, use immutable sequential names:

```text
YYYYMMDD-video-slug-stage-v001
```

Stages: rough cut, fine cut, picture lock, master QC, etc. Record in `EDITLOG.md`.

This is **not** SemVer and does **not** go in `CHANGELOG.md`.

---

## Current package version

See `pyproject.toml` and `package.json` (`0.1.0` at foundation setup).
