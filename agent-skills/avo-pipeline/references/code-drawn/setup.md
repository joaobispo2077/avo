# Set up code-drawn motion

Code-drawn is AVO's advanced option for Canvas, SVG, or optional standalone p5.brush drawing captured in headless Chrome. HyperFrames remains the built-in default. An agent needs to edit local source, compute file fingerprints and canonical JSON hashes, diagnose browser failures, and inspect actual frames. No particular model is required; a model name does not establish those capabilities.

Start with [selection](selection.md) and the [creative brief](creative.md). The [render contract](render-contract.md) defines the source and rendering responsibilities. These installed guides contain the required instructions; their supplemental [sources](sources.md) need not be reachable during render.

## Choose the installation mode

| Mode | Command prefix | What must be available |
| --- | --- | --- |
| Installed frozen engine | `avo cli` | The AVO engine with its bundled Playwright 1.64.1 package, matched driver and internal Node; separately managed Chromium; FFmpeg and FFprobe on PATH. |
| Source checkout | `python -m avo.cli` in the AVO environment | The optional `code-drawn` extra, including pinned Playwright 1.64.1; separately managed Chromium; FFmpeg and FFprobe on PATH. |

Frozen operations need neither a checkout nor an external Python or separately configured Node worker. Installing Python packages beside an existing frozen executable does not update its bundled driver. Source users can provision the extra in their checkout:

```sh
uv sync --extra code-drawn
uv run --frozen --extra code-drawn python -m avo.cli animation runtime-install --engine code-drawn --json
```

The remaining examples use the installed-engine prefix. Source users substitute `python -m avo.cli`, optionally launched through `uv run --frozen --extra code-drawn`. Do not install the unrelated PyPI package named `avo`.

## Provision only the selected runtime

Install FFmpeg and FFprobe through the operating system's package manager or a trusted portable distribution, then verify both are on PATH:

```sh
ffmpeg -version
ffprobe -version
avo cli animation runtime-install --engine code-drawn --json
avo cli animation engine-show --motion-engine code-drawn --json
```

The explicit installer runs AVO's package-matched Playwright driver to obtain managed Chromium. Downloads require network access at setup time. Render-time inputs remain local. The managed browser is separate from the engine archive; a system Chrome installation or HyperFrames' browser installation is not an automatic replacement.

Inspection never installs dependencies. Read `selection.engine`, `selection.source`, `selection.advanced` and `readiness` in the result. An unavailable runtime blocks execution and supplies repair actions. It never switches the engine. Basic Canvas/SVG does not require the optional brush library, HyperFrames, Remotion, React, GSAP, an API account, or another motion framework.

For a selected-engine prerequisite report, the native engine also exposes:

```sh
avo validate_dependencies --motion-engine code-drawn
```

This skips the other motion engines' prerequisites while retaining the existing unrelated AVO checks. Omitting `--motion-engine` retains the historical prerequisite report. Neither form changes a preference.

Playwright normally chooses its operating-system browser cache. If the environment uses `PLAYWRIGHT_BROWSERS_PATH`, keep its value consistent between installation, inspection, and rendering. Do not change `PLAYWRIGHT_NODEJS_PATH` to an external Node; AVO requires the bundled matched driver. No check command silently downloads a browser.

## Make the first standalone asset

This PowerShell example chooses a fresh external temporary project. Every filesystem argument to a code-drawn native command must be an absolute path. Replace the temporary location with a declared external animation workspace when retaining a real project.

```powershell
$motionBase = Join-Path ([System.IO.Path]::GetTempPath()) ('avo-motion-' + [guid]::NewGuid().ToString())
$motionProject = Join-Path $motionBase 'canvas-v001'
avo cli animation code-drawn-scaffold --destination $motionProject --route canvas --width 128 --height 96 --fps 30/1 --frames 12 --background opaque --background-color '#121212' --json
$motionComposition = Join-Path $motionProject 'composition.json'
$motionLock = Join-Path $motionProject 'input-lock.json'
avo cli animation code-drawn-check --composition $motionComposition --output-lock $motionLock --json
avo cli animation code-drawn-snapshot --composition $motionComposition --input-lock $motionLock --frame 5 --output (Join-Path $motionProject 'frame-0005.png') --json
avo cli animation code-drawn-render --composition $motionComposition --input-lock $motionLock --output (Join-Path $motionProject 'asset.mkv') --json
```

Expected results:

1. Scaffold creates editable route source, `assets/`, a sealed `composition.json`, and project design, storyboard, script, source/edit logs, review and delivery documents. Existing destinations are rejected without overwrite.
2. Check verifies the declared inputs, drawing bridge, ten distributed frame positions in repeat/reverse/fresh-session order, and the actual environment. It creates a new standalone input lock at the requested path.
3. Snapshot writes frame 5 as lossless PNG. Twelve frames at 30/1 represent 0.4 seconds; valid frame indices are 0 through 11.
4. Render writes a silent lossless FFV1/BGRA `asset.mkv` and `asset.generated-asset.json`. The receipt binds the original lock, source, environment and verified output.

The small dimensions are a runtime smoke example, not a production design target. Use the approved dimensions, frame rate, duration and layout for the brief. Inspect the generated image and decoded video; exit success does not approve creative quality.

Every output must use a fresh path. Repeating the scaffold against the same destination or rendering over existing output/receipt files fails. Keep editable source and actual assets; a prior rendered video is not replacement source.

Before modifying the starter, follow [source revisions and sealing](render-contract.md#revise-source-before-freezing-inputs). Editing HTML/JS/CSS or a declared asset changes its fingerprint and invalidates the old manifest. AVO currently has no native manifest-refresh command.

## SVG, transparency and brush

Use `--route svg` with a fresh destination for vectors. Canvas and SVG share the same drawing bridge and capture contract. For an overlay, use `--background transparent` and omit `--background-color`. For an opaque frame, supply the intended explicit `#rrggbb` background. Reuse real provider design values for production work.

Brush is optional. Provision it only for a brush composition:

```sh
avo cli animation runtime-install --engine code-drawn --brush --json
```

Then scaffold with `--route brush` and a new destination. This route uses the standalone WebGL2 build of p5.brush 2.2.3, without p5.js. The provisioned cache is `~/.avo/runtime/code-drawn/brush/2.2.3/`:

| Local file | SHA-256 |
| --- | --- |
| `brush.js` | `952c1853b7699e6052b9f53d917cd09ea7c35f79d9f5b25e8665a937c618caae` |
| `LICENSE.md` | `cabbece1a276329fa28ab40f1c99af3af2b7852a329551a9a485b2199616583a` |

Scaffold verifies and copies the pinned library and license into the project's declared local source closure. The global cache serves provisioning/scaffolding; a portable authored project renders its own declared bytes and does not require that cache later. Preserve the license and source-log entry with the project. A different build/version is a new dependency and requires explicit compatibility validation, not a renamed file.

The brush starter checks WebGL2, reconstructs a seeded isolated library instance and temporary drawing context for each seek, flushes rendering, copies into the stable capture surface, and releases that temporary context. Preserve this independence when extending it. Merely clearing the picture or seeding a persistent brush object did not reset every internal cache.

## Environment evidence and production handoff

The feature's recorded local evidence on 2026-10-26 used Windows with managed Chromium revision 1248 / 156.0.8078.4 and an ANGLE/NVIDIA D3D11 graphics environment. Real source tests exercised Canvas, SVG and brush, including alpha and seek checks. An extracted Windows engine archive also installed into a fresh browser cache and completed the Canvas native check/render path without a checkout or external Python. This guide does not claim an executed Linux or macOS render.

Each actual job records its own platform, driver/browser, graphics, encoder, locale, timezone and dependency identities. Do not infer pixel-identical output across operating systems or graphics drivers from one passing environment. Missing graphics/system requirements are a blocked runtime, not permission for a hidden browser/engine fallback.

The standalone commands generate graphics. Canonical placement, original footage/audio, proof reconstruction, admission, watch/transcript review and human approvals remain owned by the existing AVO pipeline. Continue through [QC and delivery](qc-delivery.md); use [troubleshooting](troubleshooting.md) for a blocked check.
