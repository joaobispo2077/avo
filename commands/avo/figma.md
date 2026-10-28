# /avo.figma Command

**Motion engine gate:** Resolve intent through [shared arguments](../../agent-skills/avo-pipeline/references/arguments.md)
before motion-specific loaders. Selected code-drawn follows the
[advanced workflow](../../agent-skills/avo-pipeline/references/code-drawn.md) and common
canonical review. HyperFrames-specific instructions below require selected
HyperFrames; unavailable engines/treatments block without silent substitution.

**Timeline integration:** Owns

## Workflow guidance

**Workflow steps:** Validate figma prerequisites → Run figma → Verify and report the figma result
**Step state source:** pipeline-run.json plus the current canonical timeline revision
**Stopping conditions:** Missing required input, a failed or stale gate, a required human decision, or verified figma completion
**Valid next commands:** /avo.motion

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

Router to the selected compatible Figma/local-asset workflow. The existing
Figma-to-HyperFrames importer applies only to selected HyperFrames; code-drawn
uses permitted frozen local assets and reports unsupported import features.

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
