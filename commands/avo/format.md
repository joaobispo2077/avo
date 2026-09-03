# /avo.format Command

**Timeline integration:** Consumes

## Workflow guidance

**Workflow steps:** Validate format prerequisites → Run format → Verify and report the format result
**Step state source:** the consumed approved artifact, delivery-manifest.json when present, and the observed result
**Stopping conditions:** Missing required input, a failed or stale gate, a required human decision, or verified format completion
**Valid next commands:** /avo.framework or /avo.pipeline

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

YouTube format diagnosis stage before editing.

**Skill:** [`agent-skills/avo-pipeline/references/format.md`](../../agent-skills/avo-pipeline/references/format.md)

---

## Usage

```
/avo.format
Provider: my-channel
The footage is at C:/Videos/my-edit
```

---

## Instructions

1. Parse `Provider` and footage location (`rawDir`).
2. Follow [`format.md`](../../agent-skills/avo-pipeline/references/format.md).

## Animation library integration

Produces the required format/viewer/promise/density/risk diagnosis used before animation pattern recommendation. Recommendations remain optional and record accept, modify, or reject.

## Shared timeline gateway

Resolves provider/video context and reads only exact approved lineage. It performs no canonical timeline mutation.
