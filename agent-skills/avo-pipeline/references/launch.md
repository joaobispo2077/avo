# /avo.launch reference

Router to **product launch / marketing URL → video** workflow.

## Required args

| Arg | Required | Example |
| --- | -------- | ------- |
| `Provider` | yes | Brand / motion tokens |
| `ProjectDir` | yes | HyperFrames project root (= `rawDir`) |
| `Source` | yes | Product URL, landing page, or brief markdown path |

## Load skill

- [`.agents/skills/product-launch-video/SKILL.md`](../../../.agents/skills/product-launch-video/SKILL.md)

Not plain explainer (`/avo.explainer`) or PR video (`/avo.pr-video`). Load skill on demand; do not duplicate body.

## Related

- Content routers: [`help.md`](help.md)
- Args: [`arguments.md`](arguments.md)
