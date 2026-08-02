# /avo.framework reference

**Animation framework intake** — HyperFrames vs Remotion before building motion.

## Preconditions

- [ ] `provider` + `rawDir` or `ProjectDir` declared
- [ ] Motion need identified (slot, content router, or custom comp)

## Load skill

- **`animation-intake-and-framework-selection`** — recommendation, rejected alternative, license/determinism risks

## Workflow

1. Diagnose format, density, existing project context, license/deployment constraints.
2. Document recommendation (HyperFrames default; Remotion only with documented reasons).
3. Write from [`docs/templates/review/framework-selection.md`](../../../docs/templates/review/framework-selection.md) → `<rawDir>/edit/review/framework-selection.md`.

## Handoff

| Outcome | Next command |
| ------- | -------------- |
| HyperFrames slot in footage edit | [`motion.md`](motion.md) |
| Custom composition | [`general.md`](general.md) or content router |
| Remotion port | [`remotion-port.md`](remotion-port.md) |
| Short motion graphic | [`motion-graphics.md`](motion-graphics.md) |

## Related

- HyperFrames policy: [`motion.md`](motion.md)
- AGENTS.md framework selection rules
