# HyperFrames Workflow

HyperFrames is the default framework for agent-authored video animation in this
repository. Use the current upstream documentation and installed official skills
before implementation because the project evolves quickly.

## Version And Skills

- Root tooling pins HyperFrames `0.7.69` in `package.json` and
  `package-lock.json` for repeatable CLI access.
- Individual scaffolded HyperFrames projects should still keep their own pinned
  `package.json` scripts so rendered deliverables remain reproducible.
- Required official skills: `/hyperframes`, `/hyperframes-core`,
  `/hyperframes-animation`, `/hyperframes-creative`, `/hyperframes-cli`, or the
  current installed equivalents.
- Current repo tooling exposes the local CLI:

```bash
npm exec -- hyperframes doctor
npm exec -- hyperframes skills update
node -p "require('./node_modules/hyperframes/package.json').version"
```

For top-level CLI help/version flags, call the local binary directly on Windows:

```powershell
& ".\node_modules\.bin\hyperframes.cmd" --version
```

## Project Structure

Use a project-local animation folder, usually under the footage project's
`edit/animations/slot_<id>/` for overlays or a dedicated animation project folder
for full compositions.

**Product-promo knowledge base:** For SaaS/product launch motion, agents load
[`exemplars/hyperframes-product-promo/README.md`](exemplars/hyperframes-product-promo/README.md)
(technique index, render contract, pre-flight checklist, lint-verified starter).
Pipeline router: [`agent-skills/avo-pipeline/references/product-promo-knowledge.md`](../agent-skills/avo-pipeline/references/product-promo-knowledge.md).
Adapted from [hyperframes-student-kit](https://github.com/nateherkai/hyperframes-student-kit);
AVO `motion-doctrine` wins on conflicts — no `.mp4` in repo.

**Short-form knowledge base:** For 9:16 talking-head + overlays + captions, load
[`exemplars/hyperframes-short-form/README.md`](exemplars/hyperframes-short-form/README.md).
Pipeline router: [`agent-skills/avo-pipeline/references/short-form-knowledge.md`](../agent-skills/avo-pipeline/references/short-form-knowledge.md).
Pairs with `/avo.shorts` footage orchestrator.

**Exemplar index:** [`exemplars/README.md`](exemplars/README.md) · CI: `bash scripts/ci/lint-hyperframes-exemplars.sh`

Suggested structure:

```text
animation-project/
  BRIEF.md
  DESIGN.md
  STORYBOARD.md
  SCRIPT.md
  ANIMATION-EDITLOG.md
  ANIMATION-SOURCE-LOG.md
  hyperframes.json
  index.html
  compositions/
  assets/
  snapshots/
  renders/
```

## Composition Contract

- Treat each composition as a timed HTML document.
- Declare composition ID, dimensions, start, duration, clips, tracks, and nested
  composition boundaries according to current HyperFrames docs.
- Use stable IDs and meaningful composition names.
- Let HyperFrames own media playback. Do not manually play, pause, or seek media.
- Use seekable GSAP timelines or supported runtime adapters.
- Keep CSS layout as the resting-state source of truth.
- Use explicit from-to animation when nested state or source state is ambiguous.

## Commands

Verify current docs before relying on exact commands. At research time, common
commands included:

```bash
npm exec -- hyperframes skills update
npm exec -- hyperframes doctor
npm exec -- hyperframes init my-video --non-interactive --example blank
npm exec -- hyperframes preview
npm exec -- hyperframes lint
npm exec -- hyperframes check
npm exec -- hyperframes snapshot --at 1,3,5
npm exec -- hyperframes render --quality draft --output draft.mp4
npm exec -- hyperframes render --quality high --fps 30 --output final.mp4
npm exec -- hyperframes render --format webm --output overlay.webm
```

Use `npm exec -- hyperframes ...` for subcommands and flags; npm 11 can strip
flag names when forwarding through `npm run` scripts. Do not use `npm exec --
hyperframes --version` as a version check because npm consumes that top-level
flag.

## Determinism

- Avoid wall-clock timing, `Math.random()`, async timeline setup, render-time
  fetches, unawaited assets, and hidden global state.
- Freeze media, data, screenshots, generated assets, and API responses before
  final render.
- Use Docker rendering when pixel consistency across machines matters.
- Use draft quality for iteration, standard for review, and high for final.

## Validation

- Run lint and check before render.
- Snapshot important times: first frame, major reveals, dense frames, captions,
  transitions, final frame, and any accessibility-risk sequence.
- Compare preview to render for layout, timing, color, fonts, missing assets,
  flicker, alpha, and audio sync.
- Use `doctor` for environment, dependency, or rendering problems.

## Setup Verification

This repo was verified with a disposable blank project at
`C:\Users\vitor\AppData\Local\Temp\opencode\hf-smoke-video-use-20260723193913`:

- `npx --yes hyperframes@0.7.69 init <dir> --non-interactive --example blank`
- `npm run check` in the scaffolded project passed with 0 errors and 0 warnings.
- `npx --yes hyperframes@0.7.69 render --quality draft --output smoke.mp4`
  produced a 10.0s H.264 MP4 at 1920x1080, 30fps.

`hyperframes doctor` reports core render dependencies present: Node.js, FFmpeg,
FFprobe, Chrome, Docker, and Docker running. Optional local Whisper, Kokoro TTS,
and MusicGen fallbacks are not installed.

## Upgrades

- Record the HyperFrames version and command output in `ANIMATION-EDITLOG.md`.
- Check upstream release/update notes before upgrading.
- Re-run lint, check, snapshots, and a render candidate after upgrades.
