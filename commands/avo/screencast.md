# /avo.screencast Command

**Timeline integration:** Profile

## Workflow guidance

**Workflow steps:** Validate screencast prerequisites → Run screencast → Verify and report the screencast result
**Step state source:** the child pipeline-run.json and its parent timeline lineage
**Stopping conditions:** Missing required input, a failed or stale gate, a required human decision, or verified screencast completion
**Valid next commands:** /avo.watch

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

Screencast / tutorial technique router (oversized cursor house style).

**Skill:** [`agent-skills/avo-pipeline/references/screencast.md`](../../agent-skills/avo-pipeline/references/screencast.md)

---

## Usage

```
/avo.screencast
Provider: my-channel
ProjectDir: /path/to/project
Source: /path/to/screencast-footage
```

---

## Instructions

1. Parse `Provider`, `ProjectDir`, `Source` (footage path or screen recording folder).
2. Follow [`screencast.md`](../../agent-skills/avo-pipeline/references/screencast.md).

## Shared timeline gateway

Runs the base pipeline with format-specific diagnosis and policy. It creates its own timeline context for derivatives and cannot bypass lineage, invalidation, Watch, transcript, or approval gates.
