# /avo.general reference

## Step/state mapping

**Durable state:** the child pipeline-run.json and its parent timeline lineage

**Workflow steps:** Validate general prerequisites → Run general → Verify and report the general result

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing required input, a failed or stale gate, a required human decision, or verified general completion

**Valid next commands:** /avo.watch

Router to **custom HyperFrames composition** (`general-video`).

## Required args

| Arg | Required | Example |
| --- | -------- | ------- |
| `Provider` | yes | Brand / motion tokens |
| `ProjectDir` | yes | HyperFrames project root |
| `Source` | yes | Composition brief, spec, or storyboard path |

## Load skill

- [`.agents/skills/general-video/SKILL.md`](../../../.agents/skills/general-video/SKILL.md)

Used for bespoke beats (e.g. pipeline demo beat C). Not a one-off motion sting ([`motion-graphics.md`](motion-graphics.md)) or slot pipeline ([`motion.md`](motion.md)).

## Related

- Framework pick first when unsure: [`framework.md`](framework.md)
- Args: [`arguments.md`](arguments.md)
