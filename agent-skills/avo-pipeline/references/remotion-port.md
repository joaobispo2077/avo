# /avo.remotion-port reference

## Step/state mapping

**Durable state:** pipeline-run.json plus the current canonical timeline revision

**Workflow steps:** Validate remotion port prerequisites → Run remotion port → Verify and report the remotion port result

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing required input, a failed or stale gate, a required human decision, or verified remotion port completion

**Valid next commands:** /avo.animation-qc

Router to **Remotion → HyperFrames port** (migration only — not full Remotion authoring).

## Required args

| Arg | Required | Example |
| --- | -------- | ------- |
| `Provider` | yes | Brand / license context |
| `ProjectDir` | yes | Target HyperFrames project root |
| `Source` | yes | Remotion project root or export folder |

## Load skill

- [`.agents/skills/remotion-to-hyperframes/SKILL.md`](../../../.agents/skills/remotion-to-hyperframes/SKILL.md)

Review Remotion license for intended use before porting. Run [`framework.md`](framework.md) when choice is not already documented.

## Related

- Args: [`arguments.md`](arguments.md)
