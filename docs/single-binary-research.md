# Research: AVO single binary (skills default runtime)

## Summary

Skills stay the product brain. Default *runtime* for those skills should be a **platform zip of the frozen AVO Python engine**, downloaded by the existing installer (not by `npx skills add`, which only copies markdown). MCP and clone+Python stay first-class alternatives. One file that also contains ffmpeg, HyperFrames, watch-skill, CUDA, and Whisper weights is not a real target.

**Research mode:** Deep
**Confidence:** High on layering and CI shape. Medium on PyInstaller + CTranslate2 until a spike.
**Last verified:** 2026-09-17

This extends [`docs/consume-modes-research.md`](consume-modes-research.md). That pass forbade advertising PyPI `avo` and kept skills + local toolchain as the one path. This pass answers *what that toolchain is* when the user never clones.

## Codebase Analysis

### Existing Patterns

| Pattern | Location | Relevance |
| --- | --- | --- |
| Two-tier install | `docs/install/README.md`, `bin/install.cjs` | Tier 1 = skills (~30s, Node ≥18). Tier 2 = clone + ffmpeg/whisper/watch-skill/HyperFrames. Binary belongs as **new default for the Python half of Tier 2**. |
| Three registry skills | `skills.json`, `agent-skills/` | `npx skills add` copies `SKILL.md` trees. No binary sidecar today. |
| Many Python entrypoints | `src/avo/*.py` `if __name__ == "__main__"` | Frozen app cannot `python -m avo.transcribe`. Need **one CLI** that covers stages + `cli` + `mcp`. |
| Timeline CLI | `src/avo/cli.py` (`prog="avo"`) | No `[project.scripts]`. Canonical invoke is `python -m avo.cli`. |
| MCP extra | `src/avo/mcp/`, `pyproject.toml` `[mcp]` | Opt-in SDK. Same process can expose `avo mcp` once frozen. |
| `repo_root()` | `src/avo/paths.py` | Walks `__file__` to `pyproject.toml`. **Breaks when frozen.** `AVO_ROOT` already exists as override. |
| Gate 1 | `config/avo.dependencies.json`, `validate_dependencies.py` | Requires `pyproject.toml` + helper files + ffmpeg + watch-skill clone + HyperFrames npm. Binary users have no clone. |
| HyperFrames adapter | `src/avo/adapters/motion/hyperframes.py` | Writes compositions then shells Node; copies GSAP from `node_modules`. Motion is **not** Python. |
| Watch adapter | `src/avo/adapters/understand/watch_skill.py` | Looks for `tools/watch-skill/.venv*/watch-skill`. Separate product. |
| ffmpeg on PATH | many modules, `ffmpeg-static` in clone | Orchestrator shells `ffmpeg`/`ffprobe`. Do not static-link into the Python exe. |
| Release | `.github/workflows/release.yml`, `release.config.mjs` | Ubuntu-only semantic-release. `@semantic-release/github` has **no assets** today. |
| Native stack | `pyproject.toml` | `faster-whisper` → CTranslate2; `numpy`; `librosa`; unused `matplotlib` still declared. |
| PyPI name | consume-modes research | Distribution name `avo` on PyPI is **Soteria**. Binary on disk can still be `avo` if scoped to `~/.avo/bin`. |

`scripts/scan-patterns.sh` still does not exist. Stack: Python 3.10+ (`src/avo/`), Node ≥18, pytest, uv/npm, GitHub Actions, semantic-release on branch `release`.

### Reusable Components

- `bin/install.cjs` + `scripts/install/install.sh|ps1` — already the skills on-ramp. Add: detect OS/arch, fetch GitHub Release zip, SHA-256, install to `~/.avo/bin`.
- `python -m avo.cli` / stage modules — what the freeze wraps.
- `avo.mcp` — same binary, `mcp` subcommand, bake the extra in.
- `config/` + `schemas/` + `avo.templates.shorts_hyperframes` — must be package data inside the freeze.
- Existing `AVO_ROOT` env — frozen layout’s config/schema home (user data dir, not a git clone).
- `ffmpeg-static` / `ffprobe-static` (npm, clone-only) — pattern for a **sidecar** ffmpeg download, not a freeze input.
- Release tags `vMAJOR.MINOR.PATCH` — natural asset URL: `…/releases/download/v1.4.0/avo-1.4.0-windows-x64.zip`.

### Conventions

- Work in `<rawDir>/edit/`, never the AVO repo.
- Skills + clone remain first-class (`docs/avo-mcp.md`).
- Windows PowerShell is a first-class install path.
- Do not tell users to `pip install avo`.
- Providers live outside the freeze (`providers/<slug>/` on disk).

## What “single binary” can and cannot mean

AVO is an **orchestrator over other engines**. Gate 1 already lists four required non-Python things: ffmpeg, watch-skill, HyperFrames (npm), Spec Kit marker.

| Piece | In the Python freeze? | Why |
| --- | --- | --- |
| `src/avo` CLI + stages (transcribe, render, shorts, grade, captions, timeline, MCP) | **Yes** | This is the requested product. |
| CPython + numpy + CTranslate2 CPU | **Yes** | Native deps of that Python. |
| `config/*.json` + `schemas/*.json` + shorts HTML templates | **Yes** | `repo_root()` / package data. |
| ffmpeg / ffprobe | **No** (sidecar or PATH) | Shell-out today. Bundling GPL ffmpeg inside the same PE/Mach-O is license + size pain. Official ffmpeg legal page: LGPL default; `--enable-gpl` changes the license of the ffmpeg build; `--enable-nonfree` is **not redistributable**. Keep a separate ffmpeg zip or “must be on PATH”. |
| faster-whisper **weights** | **No** | Hundreds of MB–GB. First transcribe downloads into HF cache (later: BL-019 sources). |
| HyperFrames + Node + GSAP | **No** | Different runtime. Adapter already `subprocess` + `node_modules/gsap`. |
| watch-skill + Bonsai GGUF | **No** | Separate CLI/venv; GGUF is user-local. |
| CUDA / GPU ctranslate2 | **No** in v1 | Qiita + production reports: CUDA stub DLLs crash CPU-only PyInstaller builds. Ship **CPU** freeze. GPU stays clone/venv. |
| Spec Kit / SDD commands | **No** | Clone-local agent chrome. |

Honest default: **“AVO engine zip.”** Marketing “one binary that renders everything” is false the moment motion or watch runs.

## External Solutions

Industry 2026: freeze **on the target OS**. No honest cross-compile for numpy/CTranslate2. Skills copy markdown; companion CLIs are downloaded from GitHub Releases by an installer (AssetsArt skills, Google `skills_lint`, Playwright browsers).

### Option 1: PyInstaller onedir zip

- **Pros**: Default for scientific Python. Official onedir is the debugable form. Hooks for numpy/matplotlib/Pillow. Build in seconds-to-minutes. GitHub matrix is well-trodden (`windows-latest`, `macos-14`/`macos-15` arm64, `macos-15-intel`). `sys.frozen` + `sys._MEIPASS` documented. Zip the folder; users run `avo.exe` / `avo` inside.
- **Cons**: Not a literal one file (onedir). Onefile extracts to `_MEI_*` every launch (slow CLI), leftover temps on crash, **cannot be notarized post-hoc** on macOS (PyInstaller #7937: nested dylibs live in an archive you cannot codesign after the fact). CTranslate2 needs `collect_all` + Windows DLL load-order care (Qiita 2026: CUDA stubs, OpenMP double-load, old `MSVCP140.dll`).
- **Effort**: Medium. Spec file + hidden imports + data files. One spike will tell if CTranslate2 is a week or a day.
- **Source**: [PyInstaller operating mode](https://pyinstaller.org/en/stable/operating-mode.html) (v6.22.3)
- **Last verified:** 2026-09-17 — High

### Option 2: Nuitka standalone (`--mode=standalone`, then maybe onefile)

- **Pros**: Compile-to-C. Faster cold start than PyInstaller onefile. Official 4.2 (2026-08) still active; Windows NSIS + macOS installer flags. Same “build on target OS” rule. `--include-data-files` for schemas.
- **Cons**: 5–15 min builds vs PyInstaller seconds (third-party 2026 comparisons). Scientific stack still needs include lists. Onefile still self-extracts. Homebrew Python on macOS is **not portable** (Nuitka user manual). Needs a C compiler on CI (MSVC / Xcode).
- **Effort**: Medium-high. Better as fallback if PyInstaller startup/size fails the spike.
- **Source**: [Nuitka use cases](https://nuitka.net/user-documentation/use-cases.html), [Nuitka 4.2](https://nuitka.net/posts/nuitka-release-42.html)
- **Last verified:** 2026-09-17 — High

### Option 3: Hatch binary builder / PyApp

- **Pros**: Official Hatch plugin. Tiny Rust stub. Easy GitHub matrix. Optional self-update. Can embed CPython (`PYAPP_DISTRIBUTION_EMBED`).
- **Cons**: Default is **runtime bootstrap**: first run downloads Python + pip-installs the project. That is *not* “no Python on the machine.” Offline first-run needs a pre-stuffed embedded distro (PyApp #117: no resolve-deps-at-build yet). User still gets a venv-shaped tree on disk, not a freeze. First-run network is a bad default for video machines.
- **Effort**: Low to ship a stub; **wrong product** unless we preinstall deps into an embedded distro (then we reinvent freeze with extra unpack).
- **Source**: [Hatch binary builder](https://hatch.pypa.io/1.18/plugins/builder/binary/), [ofek/pyapp](https://github.com/ofek/pyapp) v0.29.0 (2025-10-15)
- **Last verified:** 2026-09-17 — High

### Option 4: `uv tool install git+https://github.com/joaobispo2077/avo`

- **Pros**: Already in the uv-using clone story. Isolated env, entrypoint on PATH. No freeze bugs.
- **Cons**: Requires uv + a Python. Still not “download skills, get a binary.” Native wheels must compile/download on the user machine. Collides with “no Python.” Keep as **dev/power-user** door, not default.
- **Effort**: Tiny docs. Needs `[project.scripts]` and a **non-PyPI-avo** distribution name if ever published.
- **Source**: [uv tools](https://github.com/astral-sh/uv/blob/main/docs/concepts/tools.md)
- **Last verified:** 2026-09-17 — High

### Option 5: PyOxidizer

- **Pros**: True in-memory module load; theoretically nicer single file.
- **Cons**: Maintainer: no meaningful work since Jan 2023; “possibly dead” (discussion #740, 2024). Latest release **0.24.0 (2022-12-30)**. Windows static flavor **cannot use prebuilt `.pyd` wheels** — fatal for numpy/CTranslate2. Community still asking to archive (2026-07).
- **Effort**: Do not.
- **Source**: [PyOxidizer status #740](https://github.com/indygreg/PyOxidizer/discussions/740)
- **Last verified:** 2026-09-17 — High

### Closest analogue: skills + release sidecar

`npx skills add` will **never** attach a 200–400 MB zip. Working pattern (AssetsArt, `skills_lint`):

1. Skill install copies `SKILL.md`.
2. Installer (already `install.sh` / `install.ps1`) fetches `https://github.com/joaobispo2077/avo/releases/download/vX.Y.Z/avo-X.Y.Z-<os>-<arch>.zip`.
3. Verify SHA-256 from `SHA256SUMS`.
4. Unpack to `~/.avo/<version>/` and symlink `~/.avo/bin/avo`.
5. Skill text: “run `avo …`; if missing, re-run the installer.”

Playwright inverts the order (CLI first, skills optional). AVO keeps skills first, then **engine zip** instead of “clone the monorepo.”

## Comparison Matrix

Weights: local-first video orchestrator, Windows + macOS creators, skills as default UX.

| Criteria | Weight | PyInstaller onedir zip | Nuitka standalone | PyApp/Hatch stub | uv tool from git | PyOxidizer |
| --- | ---: | --- | --- | --- | --- | --- |
| No Python on PATH | 5 | 5 | 5 | 2 (unless fully embedded) | 0 | 5 |
| numpy / CTranslate2 survival | 5 | 4 (known but painful) | 3 | 4 (real venv) | 5 | 0 |
| macOS notarize-able | 4 | 4 onedir / 1 onefile | 4 standalone | 5 (small Mach-O) | n/a | 2 (stale) |
| CI time on every release | 3 | 5 | 2 | 5 | 5 | 1 |
| Maintained 2026 | 4 | 5 | 5 | 5 | 5 | 0 |
| Matches “one file” UX | 2 | 3 (zip of folder) | 4 onefile* | 5 stub | 1 | 5 |
| **Weighted** |  | **strong** | fallback | wrong default | keep as alt | **forbid** |

\*Nuitka/PyInstaller onefile UX is fake: extract-on-launch.

## Recommendation

**Preferred:** Frozen **onedir** AVO engine, zipped, one asset per OS/arch. Packager: **PyInstaller**. Default install: extend current curl/irm installer so **skills + engine zip** is the advertised path. MCP = `avo mcp` on that same binary. Clone + `uv run python -m avo.*` stays the contributor path.

**Alternative:** Same zip contract, Nuitka standalone if the PyInstaller spike dies on CTranslate2 or 20s cold start.

**Avoid:** PyOxidizer. Hatch/PyApp as the default (first-run pip). PyInstaller `--onefile` as the macOS artifact. Advertising that the zip replaces ffmpeg/HyperFrames/watch-skill. Publishing a wheel named `avo`. Putting `avo.exe` on the global PATH next to Soteria’s `avo`.

**Confidence:** High on the product split and CI two-stage. Medium until CTranslate2 is frozen once on `windows-latest` and `macos-14`.

### Concrete shape (v1)

**Artifacts (GitHub Release, SemVer tag already created by semantic-release):**

```text
avo-{version}-windows-x64.zip
avo-{version}-macos-arm64.zip
SHA256SUMS
```

Intel Mac (`macos-15-intel`) is optional v1.1. Windows ARM skip. Linux skip (user asked Win + macOS).

Each zip contains an onedir tree, e.g. `avo/avo.exe` + `_internal/`. Users never need to pick DLLs.

**Install layout:**

```text
~/.avo/bin/avo          → symlink/shim to current
~/.avo/current/         → unpacked onedir
~/.avo/config/          → writable copies of manifests (or first-run seed)
~/.cache/huggingface/   → whisper weights (unchanged)
```

Installer prepends `~/.avo/bin` for the agent; do **not** fight `pip install avo` on PATH.

**CLI (required before freeze):** one `__main__` / `avo` dispatcher:

```text
avo transcribe …
avo render …
avo shorts …
avo cli timeline …
avo mcp
avo version
```

Map 1:1 from today’s `python -m avo.<module>`. Skills teach `avo`, not `python -m`.

**Release pipeline (do not build binaries on the Ubuntu semantic-release job):**

1. Existing `Release` workflow tags `vX.Y.Z` (unchanged).
2. New `workflow_run` / `release: published` job: matrix `windows-latest` + `macos-14` (arm64).
3. Each job: checkout that tag, `uv sync`, PyInstaller spec, smoke `avo version` + `avo cli --help`, zip, `gh release upload`.
4. Publish `SHA256SUMS`. Signing is a **later** gate (see risks).

Cannot attach assets from the Ubuntu job: files are not on that runner (`@semantic-release/github` discussion #3417). Upload after the fact is the standard fix.

**Skills copy:**

- Registry `SKILL.md`: “Runtime: `avo` from `~/.avo/bin`. Missing? Run the installer.” Link GitHub blob, not repo-relative `SKILL.md`.
- Do **not** git-add the binary under `agent-skills/*/scripts/`.

**Code that must change for freeze (smallest set):**

1. `repo_root()` — if `sys.frozen`: user data / `AVO_ROOT` / `_MEIPASS` for bundled config+schemas; never `parents[2]` of a `.pyc` in `_internal`.
2. Gate 1 — `python-project` check is clone-only; binary mode checks `avo version` + bundled manifests + ffmpeg on PATH.
3. HyperFrames adapter — fail with “need Node + hyperframes; engine zip does not include motion” unless `node`/`hyperframes` exist. Do not copy GSAP from a missing `node_modules`.
4. Drop `matplotlib` from the **frozen** set (declared in `pyproject.toml`, unused in `src/avo`). Keep librosa only if `timeline_view` stays in the binary.
5. Bundle `config/`, `schemas/`, shorts templates (`package-data` already lists templates).

**ffmpeg policy (v1):** require on PATH (winget/choco/brew/gyan). Optional later: installer downloads an **LGPL** ffmpeg sidecar next to `~/.avo/bin`. Do not bake ffmpeg into the PE. AVO is MIT; a GPL ffmpeg **build** sitting beside the MIT zip is fine if it is a separate redistributable with its licenses; static-linking GPL ffmpeg into `avo.exe` is the thing to refuse.

## How consume modes look after this

```text
User talk  →  skills + /avo.*
                 │
                 ├─ ~/.avo/bin/avo          (default engine)
                 ├─ clone + python -m avo.* (dev)
                 └─ avo mcp / python -m avo.mcp
                        │
                        ├─ ffmpeg/ffprobe (PATH or sidecar)
                        ├─ whisper weights (cache)
                        ├─ hyperframes CLI (Node, motion only)
                        └─ watch-skill (own binary/venv)
                               │
                               ▼
                        <rawDir>/edit/
```

Same three skills. Three runtimes. Skills choose: frozen `avo` if present, else clone venv, else tell the user to install.

## Risks & Unknowns

- **CTranslate2 under PyInstaller (Windows):** access violations from CUDA stub DLLs, DLL search order, OpenMP, ancient bundled `MSVCP140`. Mitigation: CPU-only collect; exclude CUDA; spike on `windows-latest` before committing the packager.
- **`repo_root()` + Gate 1:** freeze without this is a guaranteed boot fail. Mitigation: treat as the first code change, with tests for frozen vs source.
- **macOS Gatekeeper:** unsigned download from GitHub = “cannot be opened.” Notarization needs Apple Developer ID + inside-out codesign of **onedir** (not onefile). Bare CLI cannot be stapled; Gatekeeper checks online. Ship unsigned in a private spike; **do not** call macOS GA until notarized *or* docs say `xattr -d com.apple.quarantine` as a known ugly step.
- **Windows SmartScreen:** unsigned exe = scary dialog. Azure Trusted Signing helps reputation but does not clear it on day one (Microsoft Q&A 2026). Same: optional for spike, required for “default for civilians.”
- **Size:** expect **150–400 MB** zip once numpy + CTranslate2 + librosa land. Whisper models extra. Skills install time is no longer 30s if the engine is default — label it. Optional: slim CPU freeze without librosa/matplotlib.
- **Cold start:** onedir is OK; onefile is bad for `avo --help` in an agent loop.
- **Soteria PATH collision:** `~/.avo/bin` first, never `pip install avo`.
- **HyperFrames in “render the video”:** still Node. Binary-only users can cut/transcribe/ffmpeg-render; motion stage needs Node or a later HyperFrames sidecar.
- **semantic-release job isolation:** do not expect `assets:` on the Ubuntu release job to see Windows zips.
- **Did not smoke** a real PyInstaller build of this repo in this pass.

## Suggested spike (2–4 h, before `/specify`)

On `windows-latest` (and if cheap, `macos-14`):

1. Minimal entry that imports `faster_whisper` + `avo.cli` + one shorts template file.
2. PyInstaller onedir, `collect_all` ctranslate2 + faster_whisper.
3. Run `avo version` / `--help` on a clean shell (no venv).
4. Record zip size, start time, missing-DLL errors.

Pass → write spec around PyInstaller onedir + installer download. Fail on CTranslate2 → try Nuitka standalone same afternoon, or freeze **without** transcribe (lazy split: `avo` orchestrator zip + transcribe stays venv). Ponytail default if spike fails: **do not** ship a broken all-in-one; ship orchestrator-only zip + document whisper as sidecar.

## Next Steps

1. Spike above. Do not spec packager until it boots.
2. `/specify`: freeze layout, CLI dispatcher, installer download, Gate 1 binary mode, skills copy. Explicit non-goals: ffmpeg-in-exe, HyperFrames-in-exe, GPU freeze, Linux, Intel Mac unless requested.
3. `/plan`: PyInstaller spec, `workflow_run` matrix, `gh release upload`, `repo_root()` tests.
4. Signing/notarization as a **follow-on** spec after unsigned CI works.

## Sources

| # | URL | Type | Reliability | Key finding |
| --- | --- | --- | --- | --- |
| 1 | https://pyinstaller.org/en/stable/operating-mode.html | Official | High | Onedir vs onefile extract-to-temp; no cross-OS freeze |
| 2 | https://pyinstaller.org/en/stable/runtime-information.html | Official | High | `sys.frozen`, `_MEIPASS`, `__file__` in bundles |
| 3 | https://github.com/pyinstaller/pyinstaller/issues/7937 | Issue | High | Onefile cannot be notarized post-hoc; use onedir + `--codesign-identity` |
| 4 | https://nuitka.net/user-documentation/use-cases.html | Official | High | standalone first, onefile later; no cross-compile |
| 5 | https://nuitka.net/posts/nuitka-release-42.html | Official | High | Nuitka 4.2 (2026-08) alive; installers |
| 6 | https://hatch.pypa.io/1.18/plugins/builder/binary/ | Official | High | Hatch binary = PyApp bootstrap, needs Rust |
| 7 | https://github.com/ofek/pyapp/issues/117 | Issue | High | No build-time dep resolve; embed a preinstalled distro for offline |
| 8 | https://github.com/indygreg/PyOxidizer/discussions/740 | Maintainer | High | Unmaintained since 2023; possibly dead |
| 9 | https://www.npmjs.com/package/@semantic-release/github | Official | High | `assets` globs; files must exist on that job |
| 10 | https://github.com/semantic-release/semantic-release/discussions/3417 | Discussion | High | Split build/release jobs → empty assets |
| 11 | https://www.ffmpeg.org/legal.html | Official | High | LGPL default; dynamic link + source; GPL parts optional |
| 12 | https://qiita.com/KLjp/items/1cd9260ed0e754f3dcc3 | Production | Medium | faster-whisper + PyInstaller Windows DLL crashes |
| 13 | In-repo: `pyproject.toml`, `src/avo/paths.py`, `config/avo.dependencies.json`, `bin/install.cjs`, `release.config.mjs`, `docs/consume-modes-research.md` | Primary | High | No console_scripts; repo_root; Gate 1; Ubuntu release; skills ≠ engine |
| 14 | https://github.com/google/skills_lint.dart (install pattern via search) | Official-ish | Medium | Skills markdown + separate GitHub Release binary + SHA256 |
| 15 | Azure Trusted Signing / SmartScreen Q&A 2026 | Vendor | Medium | Signing ≠ instant SmartScreen clear |

## Confidence Assessment

**Overall confidence:** Medium-high (architecture High; packager Medium)

**Reasoning:** Layering, installer hook, two-stage GitHub Release, and “do not freeze ffmpeg/HF/watch” are over-determined by this repo plus 2026 packaging docs. The remaining unknown is whether CTranslate2 survives PyInstaller on Windows without a week of DLL archaeology.

**Gaps:** No freeze of *this* tree yet. No measured zip size. No Apple/Microsoft signing account assumed. matplotlib is unused but still a declared dep.

**Suggested spike:** See above (2–4 h). If Low after the spike, split transcribe out of the freeze.

---

This pass does not re-litigate PyPI `avo`, editor MCP, or avo.cloud. It does not implement a packager.
