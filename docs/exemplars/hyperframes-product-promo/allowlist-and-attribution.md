# Source-file allowlist and attribution

## Upstream source

- **Repository:** [nateherkai/hyperframes-student-kit](https://github.com/nateherkai/hyperframes-student-kit)
- **License:** MIT (code and compositions)
- **Consulted:** 2026-08-02
- **Primary references:** `MOTION_PHILOSOPHY.md`, `CLAUDE.md`, `video-projects/clickup-demo`, `video-projects/linear-promo-30s`

## What AVO vendored (adapted excerpts)

| Source | AVO destination | Adaptation |
| ------ | --------------- | ---------- |
| `MOTION_PHILOSOPHY.md` §0–2, visual vocabulary | `technique-index.md` | Doctrine conflicts resolved; AIS hex removed |
| `MOTION_PHILOSOPHY.md` §3.8, Law #11 | `render-contract.md` | Timeline slot-fill rule adopted verbatim |
| `CLAUDE.md` render contract | `render-contract.md` | Merged with AVO determinism + seam-craft |
| `DESIGN.ais-example.md` shape | `docs/templates/animation/design-product-promo.md` | Generic tokens only |
| `clickup-demo` structure | `starter/` | Minimal 3-beat promo; no brand assets |
| Student-kit troubleshooting table | `failure-playbooks.md` | Cross-linked to HF CLI docs |

## Allowed file types in `docs/exemplars/hyperframes-product-promo/`

| Allowed | Forbidden |
| ------- | --------- |
| `.html`, `.css`, `.js` | `.mp4`, `.mov`, `.webm` |
| `.json`, `.md` | Third-party logo/background PNGs |
| Inline SVG | `.env`, API keys |
| Generic CSS custom properties | AIS hex (`#37bdf8`, `#f09025`, `#07121c`) |

## Explicit exclusions (never commit)

- `final.mp4` and anything under `renders/`
- `assets/AIS Logo PNG.png`, `AIS Background.png`, `AIS Brand Guideline Small.jpg`
- Handles and strings: `@aiautomationsociety`, `aisoc` branding in compositions
- Full `video-projects/` tree (12 projects) — link upstream instead

## Verification grep (pre-merge)

```bash
rg -n "\.mp4|#37bdf8|#f09025|#07121c|aisoc|AIS Logo|@aiautomationsociety" docs/exemplars/hyperframes-product-promo/
```

Expect zero matches.

## AIS brand note

Student-kit AIS assets remain property of AI Automation Society. Included upstream as a worked example only — not licensed for reuse in AVO deliverables.
