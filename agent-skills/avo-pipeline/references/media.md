# /avo.media reference

Thin router to **`media-use`** — resolve BGM, SFX, stock images, and brand logos before HyperFrames renders.

## Required args

| Arg | Required | Notes |
| --- | -------- | ----- |
| `Provider` | yes | Brand scope for logo resolution |
| `ProjectDir` or `rawDir` | yes | Workflow root |

## Load skill

- [`.agents/skills/media-use/SKILL.md`](../../../.agents/skills/media-use/SKILL.md)

Run **`--adopt`** first when project already has local assets to register.

## When to invoke

- Before [`motion.md`](motion.md) when using HeyGen catalog or official logo sources
- Content routers (`/avo.launch`, `/avo.music-video`, …) when skill references media-use

## Related

- SOURCE-LOG: log resolved assets in footage projects

## Canonical track integration

Inspect videoTracks before render: source/generator fingerprint, regions, z-order, fit/crop, compositing, captions/evidence safe zones, and face avoidance. Every contribution links to BMap intent; unresolved or changed sources block.
