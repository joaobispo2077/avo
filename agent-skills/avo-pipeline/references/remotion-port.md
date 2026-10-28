# /avo.remotion-port reference

**Motion engine gate:** Apply [shared arguments](arguments.md) and inspect native
`animation engine-show` with available context before motion-specific skill/setup.
HyperFrames remains the built-in default. For selected code-drawn, follow the
[advanced workflow](code-drawn.md) and common canonical source/review gates.
HyperFrames-only loaders and recipes below apply only to selected HyperFrames.
Unavailable Remotion or incompatible treatments block; never silently substitute.

This router is an explicit Remotion-to-HyperFrames source migration. Code-drawn is not an automatic port target, and the unsupported Remotion execution adapter is not enabled by porting; resolve a contrary target before authoring.

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
