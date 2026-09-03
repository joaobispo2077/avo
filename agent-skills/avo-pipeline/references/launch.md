# /avo.launch reference

## Step/state mapping

**Durable state:** the child pipeline-run.json and its parent timeline lineage

**Workflow steps:** Validate launch prerequisites → Run launch → Verify and report the launch result

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing required input, a failed or stale gate, a required human decision, or verified launch completion

**Valid next commands:** /avo.watch

Router to **product launch / marketing URL → video** workflow.

## Required args

| Arg | Required | Example |
| --- | -------- | ------- |
| `Provider` | yes | Brand / motion tokens |
| `ProjectDir` | yes | HyperFrames project root (= `rawDir`) |
| `Source` | yes | Product URL, landing page, or brief markdown path |

## Load skill

- [`.agents/skills/product-launch-video/SKILL.md`](../../../.agents/skills/product-launch-video/SKILL.md)

Not plain explainer (`/avo.explainer`) or PR video (`/avo.pr-video`). Load skill on demand; do not duplicate body.

## Related

- Content routers: [`help.md`](help.md)
- Args: [`arguments.md`](arguments.md)
