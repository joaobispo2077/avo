# /avo.screencast reference

## Step/state mapping

**Durable state:** the child pipeline-run.json and its parent timeline lineage

**Workflow steps:** Validate screencast prerequisites → Run screencast → Verify and report the screencast result

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing required input, a failed or stale gate, a required human decision, or verified screencast completion

**Valid next commands:** /avo.watch

Router to **oversized-cursor** screencast technique + tutorial format notes.

## Required args

| Arg | Required | Example |
| --- | -------- | ------- |
| `Provider` | yes | Brand |
| `ProjectDir` | yes | Workflow root (= `rawDir`) |
| `Source` | yes | Screen recording file or folder |

## Load skill

- [`.agents/skills/oversized-cursor/SKILL.md`](../../../.agents/skills/oversized-cursor/SKILL.md)

## Format notes

- Apply screencast / walkthrough diagnosis from [`guidelines-youtube.md`](guidelines-youtube.md) when tutorial-led.
- Run [`format.md`](format.md) first when format is ambiguous.
- Cursor overlay is a **technique** — not a substitute for sync ([`sync.md`](sync.md)) or captions ([`captions.md`](captions.md)).

## Related

- Pipeline motion slots: [`motion.md`](motion.md)
- Args: [`arguments.md`](arguments.md)
