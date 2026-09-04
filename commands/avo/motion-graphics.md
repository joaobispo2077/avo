# /avo.motion-graphics Command

**Timeline integration:** Profile

## Workflow guidance

**Workflow steps:** Validate motion graphics prerequisites → Run motion graphics → Verify and report the motion graphics result
**Step state source:** the child pipeline-run.json and its parent timeline lineage
**Stopping conditions:** Missing required input, a failed or stale gate, a required human decision, or verified motion graphics completion
**Valid next commands:** /avo.animation-qc

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

Router to short design-led motion graphic skill.

**Skill:** [`agent-skills/avo-pipeline/references/motion-graphics.md`](../../agent-skills/avo-pipeline/references/motion-graphics.md)

---

## Usage

```
/avo.motion-graphics
Provider: my-channel
ProjectDir: /path/to/project
Source: /path/to/brief.md
```

---

## Instructions

1. Parse `Provider`, `ProjectDir`, `Source` (brief, outline, or one-line concept).
2. Follow [`motion-graphics.md`](../../agent-skills/avo-pipeline/references/motion-graphics.md).

## Shared timeline gateway

Runs the base pipeline with format-specific diagnosis and policy. It creates its own timeline context for derivatives and cannot bypass lineage, invalidation, Watch, transcript, or approval gates.
