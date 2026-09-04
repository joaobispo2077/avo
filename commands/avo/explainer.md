# /avo.explainer Command

**Timeline integration:** Profile

## Workflow guidance

**Workflow steps:** Validate explainer prerequisites → Run explainer → Verify and report the explainer result
**Step state source:** the child pipeline-run.json and its parent timeline lineage
**Stopping conditions:** Missing required input, a failed or stale gate, a required human decision, or verified explainer completion
**Valid next commands:** /avo.watch

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

Router to faceless explainer / article → video skill.

**Skill:** [`agent-skills/avo-pipeline/references/explainer.md`](../../agent-skills/avo-pipeline/references/explainer.md)

---

## Usage

```
/avo.explainer
Provider: my-channel
ProjectDir: /path/to/explainer-project
Source: /path/to/article.md
```

---

## Instructions

1. Parse `Provider`, `ProjectDir`, `Source` (article, notes, or topic file).
2. Follow [`explainer.md`](../../agent-skills/avo-pipeline/references/explainer.md).

## Shared timeline gateway

Runs the base pipeline with format-specific diagnosis and policy. It creates its own timeline context for derivatives and cannot bypass lineage, invalidation, Watch, transcript, or approval gates.
