# Editable code-drawn starter

This is AVO's advanced motion option without a motion framework.
Canvas/SVG need no brush package. Brush adds its pinned local drawing dependency.
The browser/capture runtime and encoder remain separate prerequisites.

The drawing exposes #avo-stage, window.avoReady and window.seek(tSeconds).
Rendering reconstructs each moment independently. Preview clocks are disabled
when the host sets window.__AVO_RENDER__ before source scripts.

Use the installed native command prefixes:
- Source checkout: python -m avo.cli
- Installed engine: avo cli

Append animation code-drawn-check --composition <absolute composition.json path>
--output-lock <absolute new input-lock.json path>. Then inspect a frame through
animation code-drawn-snapshot, and render through animation code-drawn-render
with that original input lock and a fresh absolute output path.

Edit the source and refresh its manifest fingerprint/source revision before
freezing a new lock. Keep every required asset local and declared. A standalone
generated asset is not a canonical footage proof or a human approval.

Follow installed avo-pipeline references/code-drawn.md for diagnosis, safe
authoring, review and delivery. Define a real storyboard/brand before polishing.
