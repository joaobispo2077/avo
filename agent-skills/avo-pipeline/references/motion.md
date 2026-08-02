# /avo.motion reference

HyperFrames-first. Load [`hyperframes`](../../../.claude/skills/hyperframes/SKILL.md) entry + [`motion-doctrine`](../../../.claude/skills/motion-doctrine/SKILL.md) when building slots.

## Density

Default Level 2–3 for explainers; Level 1 for read-heavy segments.

## Common intents → commands

| User asks for | Command / skill |
| ------------- | --------------- |
| Liquid glass cards | [`talking-head.md`](talking-head.md) → talking-head-recut |
| Captions | [`captions.md`](captions.md) → embedded-captions |
| Logo spin / lower third | [`talking-head.md`](talking-head.md) or slot via this command |
| Logo melt / morph | [`general.md`](general.md) → general-video |
| Short motion graphic | [`motion-graphics.md`](motion-graphics.md) |
| Remotion → HyperFrames port | [`remotion-port.md`](remotion-port.md) |
| Screencast oversized cursor | [`screencast.md`](screencast.md) |
| Framework pick (HF vs Remotion) | [`framework.md`](framework.md) — run before first slot |

Run [`framework.md`](framework.md) when framework choice is not already documented.

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
