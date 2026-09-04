# /avo.explainer reference

## Step/state mapping

**Durable state:** the child pipeline-run.json and its parent timeline lineage

**Workflow steps:** Validate explainer prerequisites → Run explainer → Verify and report the explainer result

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing required input, a failed or stale gate, a required human decision, or verified explainer completion

**Valid next commands:** /avo.watch

Router to **faceless explainer** (article / notes → video).

## Required args

| Arg | Required | Example |
| --- | -------- | ------- |
| `Provider` | yes | Brand when applicable |
| `ProjectDir` | yes | Project root (= `rawDir`) |
| `Source` | yes | Article path, pasted outline file, or topic doc |

## Load skill

- [`.agents/skills/faceless-explainer/SKILL.md`](../../../.agents/skills/faceless-explainer/SKILL.md)

## Related

- Not product promo: skill routes to `/hyperframes` when intent unclear
- Args: [`arguments.md`](arguments.md)
