# Product-promo HyperFrames knowledge

Router for SaaS/product launch motion work. Load **before** building product-promo slots or running `product-launch-video`.

## When to load

- User asks for product promo, SaaS demo, feature reveal, app launch film
- `/avo.motion` slot with commercial/product message
- `/avo.launch` or `product-launch-video` workflow

## Load order

1. [`motion-doctrine`](../../../.agents/skills/motion-doctrine/SKILL.md) — multi-scene seams (always)
2. [`docs/exemplars/hyperframes-product-promo/README.md`](../../../docs/exemplars/hyperframes-product-promo/README.md) — index
3. On demand from that bundle:
   - [`technique-index.md`](../../../docs/exemplars/hyperframes-product-promo/technique-index.md)
   - [`render-contract.md`](../../../docs/exemplars/hyperframes-product-promo/render-contract.md)
   - [`pre-flight-checklist.md`](../../../docs/exemplars/hyperframes-product-promo/pre-flight-checklist.md)
   - [`failure-playbooks.md`](../../../docs/exemplars/hyperframes-product-promo/failure-playbooks.md)
4. Templates:
   - [`design-product-promo.md`](../../../docs/templates/animation/design-product-promo.md)
   - [`storyboard-product-promo.md`](../../../docs/templates/animation/storyboard-product-promo.md)
5. Reference composition: [`starter/`](../../../docs/exemplars/hyperframes-product-promo/starter/)

## Doctrine precedence

**AVO `motion-doctrine` wins** over [hyperframes-student-kit](https://github.com/nateherkai/hyperframes-student-kit) `MOTION_PHILOSOPHY.md`. Student-kit techniques are adapted — not copied wholesale. See technique-index § Doctrine precedence.

## Workflow delegation

| Intent | Primary skill / command |
| ------ | ----------------------- |
| Full URL → launch video | `product-launch-video` or [`launch.md`](launch.md) |
| Single motion slot in pipeline | [`motion.md`](motion.md) → `/avo.motion` |
| Short unnarrated motion unit | [`motion-graphics.md`](motion-graphics.md) |
| Custom multi-scene (non-launch) | [`general.md`](general.md) |

## Not in repo

- No `.mp4` reference renders — clone student-kit locally for `final.mp4` comparison
- No AIS / third-party brand assets

Attribution: [`allowlist-and-attribution.md`](../../../docs/exemplars/hyperframes-product-promo/allowlist-and-attribution.md)
