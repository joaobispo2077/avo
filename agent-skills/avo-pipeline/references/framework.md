# /avo.framework reference

## Step/state mapping

**Durable state:** pipeline-run.json plus the current canonical timeline revision

**Workflow steps:** Validate framework prerequisites → Run framework → Verify and report the framework result

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing required input, a failed or stale gate, a required human decision, or verified framework completion

**Valid next commands:** /avo.motion or /avo.general

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
