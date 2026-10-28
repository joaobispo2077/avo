# /avo.changelog-video reference

**Motion engine gate:** Apply [shared arguments](arguments.md) and inspect native
`animation engine-show` with available context before motion-specific skill/setup.
HyperFrames remains the built-in default. For selected code-drawn, follow the
[advanced workflow](code-drawn.md) and common canonical source/review gates.
HyperFrames-only loaders and recipes below apply only to selected HyperFrames.
Unavailable Remotion or incompatible treatments block; never silently substitute.

Use actual approved changelog/brand assets. Existing HyperFrames branded components remain engine-specific and require a compatible drawing implementation.

## Step/state mapping

**Durable state:** the child pipeline-run.json and its parent timeline lineage

**Workflow steps:** Validate changelog video prerequisites → Run changelog video → Verify and report the changelog video result

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing required input, a failed or stale gate, a required human decision, or verified changelog video completion

**Valid next commands:** /avo.watch

Router to **changelog → video** workflow.

## Required args

| Arg | Required | Example |
| --- | -------- | ------- |
| `Provider` | yes | Brand / motion tokens |
| `ProjectDir` | yes | Project root (= `rawDir`) |
| `Source` | yes | Path to changelog `.md` (e.g. weekly release notes) |

## Load skill

- [`.agents/skills/changelog-video/SKILL.md`](../../../.agents/skills/changelog-video/SKILL.md)

Follow skill gates; do not duplicate body here.

## Related

- Args: [`arguments.md`](arguments.md)
