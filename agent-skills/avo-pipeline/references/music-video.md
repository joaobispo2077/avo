# /avo.music-video reference

## Step/state mapping

**Durable state:** the child pipeline-run.json and its parent timeline lineage

**Workflow steps:** Validate music video prerequisites → Run music video → Verify and report the music video result

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing required input, a failed or stale gate, a required human decision, or verified music video completion

**Valid next commands:** /avo.watch

Router to **music track → visualizer / beat-sync video** workflow.

## Required args

| Arg | Required | Example |
| --- | -------- | ------- |
| `Provider` | yes | Brand when applicable |
| `ProjectDir` | yes | Project root (= `rawDir`) |
| `Source` | yes | Audio file path or video source with music bed |

## Load skill

- [`.agents/skills/music-to-video/SKILL.md`](../../../.agents/skills/music-to-video/SKILL.md)

Verify music rights in `SOURCE-LOG.md` when footage project overlaps AVO pipeline.

## Related

- Args: [`arguments.md`](arguments.md)
- Rights: [`rights.md`](rights.md) when third-party music used
