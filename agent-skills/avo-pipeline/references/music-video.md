# /avo.music-video reference

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
