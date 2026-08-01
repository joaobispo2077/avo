# /avo.motion reference

HyperFrames-first. Load [`hyperframes`](../../../.claude/skills/hyperframes/SKILL.md) entry + [`motion-doctrine`](../../../.claude/skills/motion-doctrine/SKILL.md) when building slots.

## Density

Default Level 2–3 for explainers; Level 1 for read-heavy segments.

## Common intents → skills

| User asks for | Skill path |
| ------------- | ---------- |
| Liquid glass cards | talking-head-recut + HyperFrames |
| Captions | embedded-captions |
| Logo spin / lower third | talking-head-recut overlay |
| Logo melt / morph | Custom HyperFrames composition |

## Slot layout

```
edit/animations/slot_<id>/
  spec.md
  composition/
  render.mp4
```

Spawn **parallel** sub-agents for multiple slots (SKILL Hard Rule 10).

## Examples shipped in command

- Cursor logo → liquid glass card spin
- OpenAI logo from folder → melt into verdict card

Preserve brand assets; never invent trademarked logos when user supplies a path.
