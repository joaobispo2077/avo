# Code-drawn motion (advanced)

Use this entry when the native effective engine is `code-drawn`. HyperFrames remains
AVO's built-in default. Code-drawn is an advanced option for authors who want to
create motion without HyperFrames or Remotion. Canvas, SVG and optional standalone
p5.brush are drawing routes within this one engine, not additional engines.

Advanced describes responsibility, not an approval gate. Explain the trade-offs
once and proceed within the user's authorized request. Any model or agent that can
write, run and inspect the required source can use this route; no model brand,
premium effort mode, waiting period or marketing claim is a prerequisite.

## Select before loading a motion workflow

Read [shared arguments](arguments.md), normalize only the current user's direct
instruction, then use native `animation engine-show` before engine-specific skill
loads, installs or authoring. See [selection](code-drawn/selection.md) for the
complete instruction matrix, scope rules and command suffixes.

- Direct "no frameworks", "without a framework", "framework-free", or unqualified
  "avoid HyperFrames" selects invocation `code-drawn`.
- "Avoid HyperFrames; use Remotion" selects `remotion`. Report its actual readiness;
  the current AVO Remotion adapter is unsupported. Never substitute another engine.
- No animation/skip motion, a capability question, quoted source material and a
  negated exclusion have different meanings. Contradictory explicit choices need
  one focused clarification before engine-dependent changes.
- With no invocation selection, resolve project > provider/channel > global >
  built-in HyperFrames. A one-run choice does not save a default.

For a code-drawn result, continue here and in the relevant linked sections. Do not
load HyperFrames skills, its motion doctrine, init/install or framework-owned kits
as prerequisites. A HyperFrames-specific treatment may be unavailable on this
route; describe the capability gap before creating source. AVO does not convert
existing kits or Remotion projects automatically.

## What the author owns

You own complete drawing state at an arbitrary time, seeded randomness, asset/font
readiness, readable composition and holds, alpha/color decisions and inspection of
actual rendered output. "No motion framework" does not mean no dependencies, no
animation, or no pipeline gates. The runtime uses pinned Playwright with its
bundled driver, matched managed Chromium, FFmpeg/FFprobe and local editable source.
Optional brush adds its pinned standalone script/license and WebGL2 requirement;
plain Canvas/SVG do not require p5.js, brush or a motion framework.

Freeze fonts, images, data and dependencies locally. Browser pages draw generated
visuals only: do not play original footage, earlier proofs or browser audio inside
them. Source-derived stills need permitted extraction provenance. The canonical
picture/audio and factual meaning remain under AVO's existing owners.

## Editable inputs and authoring capabilities

The authoring agent needs to inspect/edit local HTML, JavaScript, SVG and JSON,
compute file SHA-256/byte sizes and the manifest's canonical JSON content seal,
run the selected native commands, and inspect actual frames/playback. A text-only
tool that cannot run or view results must report those limits; source generation
alone is not a checked animation.

The native frozen commands do not require an external Python. Use compatible
file/hash/JSON tools available to the authoring agent; a source-checkout Python
helper is an optional development tool, not a repair requirement for binary users.

After changing source, assets or dependencies, update their exact declared
`sha256`/`sizeBytes`, describe the new `sourceRevision` and recompute `manifestHash`
using AVO's canonical content rule with that field excluded. See
[the render contract](code-drawn/render-contract.md) for the complete identity and
serialization rules. Check validates existing identities; it does not refresh
them, overwrite an old input lock or supply an undocumented refresh command.

Scaffolding writes target dimensions, frame rate/count, background and seed into
editable source constants. Later manifest edits do not automatically rewrite or
inject those constants. Keep the page and manifest in agreement when changing
targets or seeded drawing behavior, then refresh fingerprints and make a new
immutable lock. A recorded seed is useful only if the drawing actually uses it
with independent state. Prefer a fresh scaffold for a changed target when that is
simpler than adapting an existing composition.

## Working loop

For an installed engine, the prefix is `avo cli`. In an AVO source checkout use
`python -m avo.cli` instead. The suffixes are identical; frozen users need neither
an external Python nor an AVO checkout. Replace the quoted placeholders with
absolute paths in the declared external project, normally under `edit/`.

1. Inspect the selection and selected prerequisites. Provision only explicitly
   through `animation runtime-install --engine code-drawn`; add `--brush` only when
   required. Inspection/check/render do not download missing dependencies.
2. Diagnose format, viewer, purpose, evidence, brand, density, target dimensions,
   rational frame rate and frame count. Reuse the provider's actual design assets.
   Plan scene/state lists and readable holds before implementing a long sequence.
3. Scaffold a new destination with `animation code-drawn-scaffold`. Edit its local
   source, `composition.json`, design/storyboard and source/change logs. The scaffold
   refuses to overwrite an existing directory.
4. Run `animation code-drawn-check`, inspect representative snapshots and freeze a
   new immutable input lock. A changed input needs a new lock and new evidence.
5. Render from that exact lock, inspect decoded pixels and actual output, and keep
   the editable source, dependencies, lock and generated-asset receipt together.

A small opaque Canvas example follows. Its color is an example setting; use the
real project palette for production.

```text
avo cli animation runtime-install --engine code-drawn --json
avo cli animation code-drawn-scaffold --destination "<new-absolute-directory>" --route canvas --width 1280 --height 720 --fps 30/1 --frames 90 --background opaque --background-color "#121212" --json
avo cli animation code-drawn-check --composition "<absolute-directory>/composition.json" --output-lock "<absolute-directory>/input-lock.json" --json
avo cli animation code-drawn-snapshot --composition "<absolute-directory>/composition.json" --input-lock "<absolute-directory>/input-lock.json" --frame 30 --output "<absolute-directory>/frame-0030.png" --json
avo cli animation code-drawn-render --composition "<absolute-directory>/composition.json" --input-lock "<absolute-directory>/input-lock.json" --output "<absolute-directory>/asset.mkv" --json
```

The output is silent, lossless FFV1/BGRA Matroska plus
`asset.generated-asset.json`. For an overlay use `--background transparent` and omit
the opaque color; verify actual decoded alpha and the final composite. Frame
indices are integers: `0 <= frame < frameCount`. The endpoint at duration is not an
extra output frame. The initial supported quality is one spatial sample and one
temporal sample; unsupported requests fail rather than claiming motion blur.

## Pipeline boundary and review

A successful standalone check/render produces a generated asset, not an approved
footage proof or a completed pipeline. BMap/Tracks own editorial placement; the
composition owns local drawing time. Canonical integration must bind exact current
CMap, BMap, Tracks, Animation, Sync Map, original source fingerprints, generator
inputs and render contract through the shared coordinator and ProofPlan. A caller
cannot turn a standalone lock into canonical authority by editing JSON.

Every proof is reconstructed from canonical originals and verifiable current
intermediates. Prior proofs/masters are review references only. Preserve the
canonical audio mix, source-resolution policy, Watch plus candidate transcript
analysis, rights/accessibility checks and explicit human approvals. Changing an
engine deliberately revises affected work through existing invalidation services;
changing a saved future default does not rewrite pinned animation.

## Guide map

| Guide | Use it for |
| --- | --- |
| [Selection](code-drawn/selection.md) | Engine IDs, intent, scopes, inspection and run/pinned-work behavior. |
| [Setup](code-drawn/setup.md) | Source/frozen runtime, managed browser, local assets/fonts and optional brush. |
| [Render contract](code-drawn/render-contract.md) | Manifest, ready/seek bridge, frame math, state, locks and output. |
| [Creative direction](code-drawn/creative.md) | Diagnosis, references, provider design, storyboard and target layouts. |
| [Motion techniques](code-drawn/motion-techniques.md) | Deterministic easing, continuity, reveals, stagger and limits. |
| [Audio](code-drawn/audio.md) | Measured cues, uncertainty, canonical mix and source records. |
| [QC and delivery](code-drawn/qc-delivery.md) | Stills, transition strips, small-display checks, critique and human gates. |
| [Troubleshooting](code-drawn/troubleshooting.md) | Runtime/assets, graphics, seeking, alpha, encoding, stale inputs and cancellation. |
| [Sources](code-drawn/sources.md) | Article adaptation, technical versions, provenance and verified behavior. |

Apply the shared [response contract](step-status.md) when reporting workflow state.

## Native canonical generation and candidate samples

Once the current canonical strategy and Tracks bind the same local instance/manifest, use `avo cli animation materialize --project <absolute project> --instance-id <instance> --output <new absolute edit/derived/asset.mkv> --json`. The coordinator verifies current CMap/Sync approvals, freezes the original canonical lock, renders and admits the receipt. It accepts no caller-supplied canonical binding and changes no lifecycle stage. The pipeline stage `motion-materialize` accepts payload keys `instanceId` and `output` through that same coordinator.

For exact candidate samples, use `avo cli animation code-drawn-review --candidate <absolute video> --source-receipt <absolute generated receipt> --output <new absolute review directory> --json`; add `--project <absolute project>` for canonical assets, repeat `--source-receipt` for additional drawing ancestors, and request `--sample-frame <integer>`, `--transition <start:end-exclusive>` or `--loop` only as needed. This writes decoded frame/contact-sheet/small-display evidence and requested transition/loop strips. The package remains pending human judgment with no creator approval; follow [QC/delivery](code-drawn/qc-delivery.md).

For a canonical composite candidate, provide `--project <absolute project> --materialization <absolute native materialization.json>` to `animation code-drawn-review`; it verifies the exact frozen candidate and all used drawing ancestors. Without materialization context the candidate must be the exact generated asset from its single receipt. Use `--render-profile master` when preparing a package for delivery. Native `deliver prepare --motion-review <absolute code-drawn-review.json>` attaches its source/runtime/output metadata while retaining all existing full review and creator gates. Manual existing-master/human-final adoption keeps its existing assembly compatibility limit.
