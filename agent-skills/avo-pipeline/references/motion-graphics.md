# /avo.motion-graphics reference

## Step/state mapping

**Durable state:** the child pipeline-run.json and its parent timeline lineage

**Workflow steps:** Validate motion graphics prerequisites → Run motion graphics → Verify and report the motion graphics result

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing required input, a failed or stale gate, a required human decision, or verified motion graphics completion

**Valid next commands:** /avo.animation-qc

Router to **short design-led motion graphic** workflow.

## Required args

| Arg | Required | Example |
| --- | -------- | ------- |
| `Provider` | yes | Brand / motion tokens |
| `ProjectDir` | yes | HyperFrames project root |
| `Source` | yes | Brief path or one-line concept |

## Load skill

- [`.agents/skills/motion-graphics/SKILL.md`](../../../.agents/skills/motion-graphics/SKILL.md)

Distinct from pipeline slot work ([`motion.md`](motion.md)) and talking-head overlays ([`talking-head.md`](talking-head.md)). Load skill on demand; do not duplicate body.

## Related

- Slot-based motion: [`motion.md`](motion.md)
- Args: [`arguments.md`](arguments.md)
