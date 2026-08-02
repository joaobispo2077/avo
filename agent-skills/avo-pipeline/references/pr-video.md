# /avo.pr-video reference

Thin router to **PR → video** content workflow. Input is a code change, not camera footage.

## Required args

| Arg | Required | Example |
| --- | -------- | ------- |
| `Provider` | yes | Brand when compositions use provider assets |
| `ProjectDir` | yes | HyperFrames project root (= `rawDir` semantics) |
| `Source` | yes | `https://github.com/owner/repo/pull/42` or `owner/repo#42` |

**Private repos:** require authenticated `gh` — warn user; never embed tokens in logs.

## Load skill

- [`.agents/skills/pr-to-video/SKILL.md`](../../../.agents/skills/pr-to-video/SKILL.md)

Do **not** duplicate skill steps here. Load skill on demand; follow its gates.

## Output location

Per skill: compositions and renders under `ProjectDir` (not AVO repo).

## Related

- Content routers: [`help.md`](help.md) **Content** section
- Args: [`arguments.md`](arguments.md) — `ProjectDir`, `Source`
