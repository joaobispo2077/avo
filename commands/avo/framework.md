# /avo.framework Command

**Timeline integration:** Owns

## Workflow guidance

**Workflow steps:** Validate framework prerequisites → Run framework → Verify and report the framework result
**Step state source:** pipeline-run.json plus the current canonical timeline revision
**Stopping conditions:** Missing required input, a failed or stale gate, a required human decision, or verified framework completion
**Valid next commands:** /avo.motion or /avo.general

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

Animation framework intake — HyperFrames vs Remotion diagnosis.

**Skill:** [`agent-skills/avo-pipeline/references/framework.md`](../../agent-skills/avo-pipeline/references/framework.md)

---

## Usage

```
/avo.framework
Provider: my-channel
The footage is at C:/Videos/my-edit
```

---

## Instructions

1. Parse `Provider` and footage location (`rawDir`).
2. Follow [`framework.md`](../../agent-skills/avo-pipeline/references/framework.md).

## Animation library integration

Records the selected framework, determinism assumptions, packages, licensing checks, and render boundary in the per-video animation strategy; framework choice has no timing authority.

## Shared timeline gateway

Resolves provider/video context and records the framework choice in the video Animation strategy through the shared service; it never owns BMap timing.
