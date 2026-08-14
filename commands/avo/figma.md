# /avo.figma Command

**Timeline integration:** Owns

Router to Figma → HyperFrames import workflow.

**Skill:** [`agent-skills/avo-pipeline/references/figma.md`](../../agent-skills/avo-pipeline/references/figma.md)

---

## Usage

```
/avo.figma
Provider: my-channel
ProjectDir: /path/to/composition
Source: https://www.figma.com/file/...
```

---

## Instructions

1. Parse `Provider`, `ProjectDir`, `Source` (Figma file URL or export path).
2. Follow [`figma.md`](../../agent-skills/avo-pipeline/references/figma.md).

## Canonical track integration

Figma assets/components are fingerprinted inputs referenced by video layers and animation strategy; they never bypass BMap timing authority.

## Shared timeline gateway

Uses shared timeline storage, transition guards, invalidation, and AI review services. It cannot maintain private CMap, BMap, sync, track, animation, or approval truth.
