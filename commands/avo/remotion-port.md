# /avo.remotion-port Command

**Timeline integration:** Owns

## Workflow guidance

**Workflow steps:** Validate remotion port prerequisites → Run remotion port → Verify and report the remotion port result
**Step state source:** pipeline-run.json plus the current canonical timeline revision
**Stopping conditions:** Missing required input, a failed or stale gate, a required human decision, or verified remotion port completion
**Valid next commands:** /avo.animation-qc

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

Router to Remotion → HyperFrames port workflow (migration only).

**Skill:** [`agent-skills/avo-pipeline/references/remotion-port.md`](../../agent-skills/avo-pipeline/references/remotion-port.md)

---

## Usage

```
/avo.remotion-port
Provider: my-channel
ProjectDir: /path/to/project
Source: /path/to/remotion-project
```

---

## Instructions

1. Parse `Provider`, `ProjectDir`, `Source` (Remotion project root or composition export).
2. Follow [`remotion-port.md`](../../agent-skills/avo-pipeline/references/remotion-port.md).

## Canonical track integration

Imported components become fingerprinted animation/video-layer references. BMap remains the sole creative timing authority and the generated EDL remains the render projection.

## Shared timeline gateway

Uses shared timeline storage, transition guards, invalidation, and AI review services. It cannot maintain private CMap, BMap, sync, track, animation, or approval truth.
