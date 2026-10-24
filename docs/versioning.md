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

Releases are **automated** via [semantic-release](https://github.com/semantic-release/semantic-release)
(maxframe-style). After **CI** succeeds:

| Branch | Channel | Example tag |
|--------|---------|-------------|
| `develop` | Alpha prerelease | `v0.2.0-alpha.1` |
| `release` | Stable | `v0.2.0` |

1. Workflow `.github/workflows/release.yml` runs (`workflow_run` after **CI**, or manual dispatch)
2. `semantic-release --dry-run` skips the job when there are no releasable Conventional Commits
3. `npm run release` (see `release.config.mjs`) bumps `package.json` + `pyproject.toml`, updates
   `CHANGELOG.md`, creates the git tag, and publishes the GitHub Release
4. `scripts/ci/verify-release-version.sh` confirms manifest alignment post-release

The GitHub Release initially stays **draft**. The release workflow dispatches
`engine-binary.yml` with `attach_tag` set to the existing version tag. After all
three platform builds pass, that workflow uploads their zip files and checksums,
then publishes the draft. Until publication finishes, GitHub's latest-release
badge continues to show the previous published version.

The engine workflow intentionally skips its work-selection job for releases.
Its publishing condition must explicitly handle that skipped ancestor with
`!cancelled()` while requiring `needs.zip-smoke.result == 'success'`. Failed,
cancelled or skipped builds must never publish a release. Manual smoke runs
without `attach_tag`, push runs and pull-request runs must not publish either.

To recover an existing draft after fixing the workflow, dispatch **Engine binary**
from a branch containing the fix and set `attach_tag` to that draft's existing tag
(for example, `v1.17.0`). The builds check out that tag, not the workflow branch's
application code. This recovery attaches assets and publishes the existing
release without creating another version or changing its tag.

**Maintainer setup:** add repository secret **`GH_TOKEN`** (PAT or fine-grained token with
`contents: write`). Maxframe uses the same pattern; `github.token` alone may be insufficient
for `@semantic-release/git` pushes.

**Local dry-run (no publish):**

```bash
npm ci
npm run release:dry-run
# or: npm run release:local
```

**Emergency manual tag** (discouraged — bypasses semantic-release):

```bash
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

See `pyproject.toml` and `package.json` (`1.0.0` public baseline).
