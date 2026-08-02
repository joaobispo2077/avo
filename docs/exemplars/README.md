# HyperFrames exemplars index

Committed reference compositions and knowledge bundles for AVO agents. **Authoring sources only** — no `.mp4` in git.

| Bundle | Format | Path |
| ------ | ------ | ---- |
| Product promo | 16:9 SaaS / launch | [`hyperframes-product-promo/`](hyperframes-product-promo/README.md) |
| Short-form vertical | 9:16 talking-head + overlays | [`hyperframes-short-form/`](hyperframes-short-form/README.md) |

## CI

Both starters are lint-gated in CI:

```bash
bash scripts/ci/lint-hyperframes-exemplars.sh
```

## Pipeline routers

- [`agent-skills/avo-pipeline/references/product-promo-knowledge.md`](../../agent-skills/avo-pipeline/references/product-promo-knowledge.md)
- [`agent-skills/avo-pipeline/references/short-form-knowledge.md`](../../agent-skills/avo-pipeline/references/short-form-knowledge.md)

## Shared rules

- [`hyperframes-product-promo/render-contract.md`](hyperframes-product-promo/render-contract.md) applies to all HyperFrames work
- **AVO `motion-doctrine` wins** over student-kit aesthetics

## Upstream

Adapted from [hyperframes-student-kit](https://github.com/nateherkai/hyperframes-student-kit) (MIT). See each bundle's `allowlist-and-attribution.md`.

Spec: [`specs/active/avo-motion-knowledge/`](../specs/active/avo-motion-knowledge/) · Phase 2: [`specs/active/avo-motion-knowledge-phase2/`](../specs/active/avo-motion-knowledge-phase2/)
