# /avo.slideshow reference

## Step/state mapping

**Durable state:** the child pipeline-run.json and its parent timeline lineage

**Workflow steps:** Validate slideshow prerequisites → Run slideshow → Verify and report the slideshow result

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing required input, a failed or stale gate, a required human decision, or verified slideshow completion

**Valid next commands:** /avo.watch

Router to **slideshow / presentation** HyperFrames workflow.

## Required args

| Arg | Required | Example |
| --- | -------- | ------- |
| `Provider` | yes | Brand / design system |
| `ProjectDir` | yes | Project root (= `rawDir`) |
| `Source` | yes | Slide outline, deck notes, or structured markdown |

## Load skill

- [`.agents/skills/slideshow/SKILL.md`](../../../.agents/skills/slideshow/SKILL.md)

## Related

- Args: [`arguments.md`](arguments.md)
