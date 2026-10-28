# /avo.general reference

**Motion engine gate:** Apply [shared arguments](arguments.md) and inspect native
`animation engine-show` with available context before motion-specific skill/setup.
HyperFrames remains the built-in default. For selected code-drawn, follow the
[advanced workflow](code-drawn.md) and common canonical source/review gates.
HyperFrames-only loaders and recipes below apply only to selected HyperFrames.
Unavailable Remotion or incompatible treatments block; never silently substitute.

ProjectDir is an editable project directory for the selected engine. A code-drawn custom composition uses its own local manifest/source contract, not HyperFrames project initialization.

## Step/state mapping

**Durable state:** the child pipeline-run.json and its parent timeline lineage

**Workflow steps:** Validate general prerequisites → Run general → Verify and report the general result

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing required input, a failed or stale gate, a required human decision, or verified general completion

**Valid next commands:** /avo.watch

Router to a custom composition. The selected HyperFrames branch uses `general-video`; code-drawn uses its portable workflow.

## Required args

| Arg | Required | Example |
| --- | -------- | ------- |
| `Provider` | yes | Brand / motion tokens |
| `ProjectDir` | yes | Selected-engine project root |
| `Source` | yes | Composition brief, spec, or storyboard path |

## Selected HyperFrames skill

- [`.agents/skills/general-video/SKILL.md`](../../../.agents/skills/general-video/SKILL.md)

Used for bespoke beats (e.g. pipeline demo beat C). Not a one-off motion sting ([`motion-graphics.md`](motion-graphics.md)) or slot pipeline ([`motion.md`](motion.md)).

## Related

- Framework pick first when unsure: [`framework.md`](framework.md)
- Args: [`arguments.md`](arguments.md)
