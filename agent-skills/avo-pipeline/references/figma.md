# /avo.figma reference

## Step/state mapping

**Durable state:** pipeline-run.json plus the current canonical timeline revision

**Workflow steps:** Validate figma prerequisites → Run figma → Verify and report the figma result

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing required input, a failed or stale gate, a required human decision, or verified figma completion

**Valid next commands:** /avo.motion

Router to **Figma import → HyperFrames composition** workflow.

## Required args

| Arg | Required | Example |
| --- | -------- | ------- |
| `Provider` | yes | Brand tokens when applicable |
| `ProjectDir` | yes | HyperFrames project root |
| `Source` | yes | Figma file URL or exported frame assets path |

## Load skill

- [`.agents/skills/figma/SKILL.md`](../../../.agents/skills/figma/SKILL.md)

Import-only v1 — full motion polish may continue via [`motion.md`](motion.md).

## Related

- Args: [`arguments.md`](arguments.md)
