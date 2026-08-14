# /avo.media Command

**Timeline integration:** Owns

Router to media-use for BGM, SFX, images, and brand logos from catalogs.

**Skill:** [`agent-skills/avo-pipeline/references/media.md`](../../agent-skills/avo-pipeline/references/media.md)

---

## Usage

```
/avo.media
Provider: my-channel
ProjectDir: /path/to/project
```

Optional: `--adopt` to register existing assets

---

## Instructions

1. Invoke before motion or content renders needing licensed/catalog media.
2. Follow [`media.md`](../../agent-skills/avo-pipeline/references/media.md) and load **`media-use`** skill.

## Canonical track integration

Registers content fingerprints first, then creates BMap cues and resolved track regions. Missing or changed media blocks the affected output; AVO never substitutes a same-named asset.

## Shared timeline gateway

Uses shared timeline storage, transition guards, invalidation, and AI review services. It cannot maintain private CMap, BMap, sync, track, animation, or approval truth.
