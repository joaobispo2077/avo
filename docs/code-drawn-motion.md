# Code-drawn motion

HyperFrames remains AVO's built-in default. Advanced `code-drawn` motion uses
Canvas, SVG or optional standalone p5.brush with managed headless Chromium,
without HyperFrames or Remotion. The current Remotion execution adapter is
unsupported; selecting or saving its name does not enable a renderer.

Keep the existing `/avo.motion`, `/avo.pipeline` and `/avo.framework` entry points.
The portable `avo-pipeline` guidance owns the workflow:

| Need | Maintained guide |
| --- | --- |
| Start and understand advanced responsibilities | [Entry](../agent-skills/avo-pipeline/references/code-drawn.md) |
| Inspect/set/reset scoped choices and one-run overrides | [Selection](../agent-skills/avo-pipeline/references/code-drawn/selection.md) |
| Install only the selected runtime and optional brush dependency | [Setup](../agent-skills/avo-pipeline/references/code-drawn/setup.md) |
| Author deterministic drawing, alpha and frozen locks | [Render contract](../agent-skills/avo-pipeline/references/code-drawn/render-contract.md) |
| Diagnose brand, references, scene states and layouts | [Creative direction](../agent-skills/avo-pipeline/references/code-drawn/creative.md) |
| Choose deterministic motion techniques | [Motion techniques](../agent-skills/avo-pipeline/references/code-drawn/motion-techniques.md) |
| Preserve canonical audio and measure cues | [Audio](../agent-skills/avo-pipeline/references/code-drawn/audio.md) |
| Review actual frames/composites and deliver editable source | [QC and delivery](../agent-skills/avo-pipeline/references/code-drawn/qc-delivery.md) |
| Diagnose failed or stale attempts | [Troubleshooting](../agent-skills/avo-pipeline/references/code-drawn/troubleshooting.md) |
| Article adaptations and dependency references | [Sources](../agent-skills/avo-pipeline/references/code-drawn/sources.md) |

Exact native commands are in the [command index](avo-commands.md#native-motion-commands).
Preference inspection and global set/reset need no footage project. Installed
engines use `avo cli`; checkout execution uses `python -m avo.cli`.

Standalone generation does not establish canonical admission, automated Shorts
support or approval. Use only native paths that support the selected operation
and verify current source/locks; report a missing capability before authoring
or rendering. Existing canonical timing, source reconstruction, Watch/transcript
evidence, explicit human decisions and delivery authority remain in force.

## Canonical motion and review

For an external canonical project, author a logical code-drawn component under `edit/derived/components/<instance>/.../composition.json`. Animation stores its instance/manifest fingerprint; the matching Tracks `generatedSourceRef` owns its BMap-bound region and placement. Current CMap and Sync approvals remain required.

```text
avo cli animation materialize --project <absolute avo.project.json> --instance-id <instance> --output <new absolute edit/derived/asset.mkv> --json
```

This native coordinator creates the original canonical input lock, captures the drawing and admits its receipt without advancing the pipeline or granting approval. `pipeline stage --stage motion-materialize` accepts a payload with `instanceId` and `output` through the same port. Frozen ProofPlans use `generated-clip` for opaque bases or `overlay-video` for straight-alpha overlays, with exact receipt/lock/source-frame references; partial proofs preserve phase across cuts and preserve canonical audio. Unsupported audio/event envelopes fail before output.

Create visual samples from the exact candidate with `avo cli animation code-drawn-review --candidate <absolute candidate> --source-receipt <absolute generated receipt> --output <new absolute review directory> --json`. Repeat `--source-receipt` for multiple drawing ancestors; add `--project` for canonical assets. Optional `--sample-frame`, `--transition start:end`, and `--loop` request particular frames/strips. The resulting `code-drawn-review.json` binds actual decoded frames, contact sheets and small-display views to the candidate and source identities; it starts pending human judgment with no approval. Continue through existing Watch, transcript, accessibility, rights and creator gates.

For a canonical composite candidate, provide `--project <absolute project> --materialization <absolute native materialization.json>` to `animation code-drawn-review`; it verifies the exact frozen candidate and all used drawing ancestors. Without materialization context the candidate must be the exact generated asset from its single receipt. Use `--render-profile master` when preparing a package for delivery. Native `deliver prepare --motion-review <absolute code-drawn-review.json>` attaches its source/runtime/output metadata while retaining all existing full review and creator gates. Manual existing-master/human-final adoption keeps its existing assembly compatibility limit.
