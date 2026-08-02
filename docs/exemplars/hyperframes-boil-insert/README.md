# HyperFrames boil-insert knowledge base

Curated in-repo knowledge for **wiggly / boiling timed insertions** (text, images, video) composited onto any AVO video via EDL overlays.

## Load order (agents)

1. [`motion-doctrine`](../../../.agents/skills/motion-doctrine/SKILL.md) — always first
2. [`render-contract.md`](render-contract.md) — overlay + determinism rules
3. [`technique-index.md`](technique-index.md) — DaVinci mapping, presets, doctrine note
4. [`pre-flight-checklist.md`](pre-flight-checklist.md) — before preview/render
5. [`lib/`](lib/) — canonical modules (copied to `starter/lib/` per HF project root)
6. [`starter/`](starter/) — text callout reference
7. [`starter-image/`](starter-image/) — image sticker reference
8. [`failure-playbooks.md`](failure-playbooks.md) — when lint/render fails
9. [`composite-validation.md`](composite-validation.md) — EDL + FFmpeg composite QC

Pipeline router: [`agent-skills/avo-pipeline/references/boil-insert-knowledge.md`](../../../agent-skills/avo-pipeline/references/boil-insert-knowledge.md)

## Doctrine precedence

**AVO `motion-doctrine` wins.** Boil on a **timed insert** is allowed stylistic treatment — not banned idle scene wobble. Boil runs only during the documented hold window.

## Slot layout (footage projects)

```
edit/animations/slot_<id>/
  spec.md
  composition/    # copy from starter or starter-image
  render.webm       # alpha overlay export
```

Register in `edit/edl.json` → `overlays[]` with `anchor_in_source`, `motion_brief_id`.

## What is not here

- Full-program boiling captions (future `embedded-captions` theme)
- FFmpeg procedural boil in `render.py`
- Rendered `.mp4`/`.webm` binaries (authoring sources only)
