# /avo.general Command

**Timeline integration:** Profile

## Workflow guidance

**Workflow steps:** Validate general prerequisites → Run general → Verify and report the general result
**Step state source:** the child pipeline-run.json and its parent timeline lineage
**Stopping conditions:** Missing required input, a failed or stale gate, a required human decision, or verified general completion
**Valid next commands:** /avo.watch

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

Router to custom HyperFrames composition skill.

**Skill:** [`agent-skills/avo-pipeline/references/general.md`](../../agent-skills/avo-pipeline/references/general.md)

---

## Usage

```
/avo.general
Provider: my-channel
ProjectDir: /path/to/project
Source: /path/to/composition-brief.md
```

---

## Instructions

1. Parse `Provider`, `ProjectDir`, `Source` (brief, spec, or storyboard path).
2. Follow [`general.md`](../../agent-skills/avo-pipeline/references/general.md).

## Shared timeline gateway

Runs the base pipeline with format-specific diagnosis and policy. It creates its own timeline context for derivatives and cannot bypass lineage, invalidation, Watch, transcript, or approval gates.
