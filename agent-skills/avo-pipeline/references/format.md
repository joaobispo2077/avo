# /avo.format reference

**Format diagnosis stage** — structured playbook selection before pacing or style decisions.

Distinct from [`guidelines.md`](guidelines.md) (rules reference). Produces a per-project artifact.

## Preconditions

- [ ] `provider` + `rawDir` declared
- [ ] Title/thumbnail promise or working title available

## Load skill

- **`youtube-format-selection`** — primary + hybrid formats, viewer promise, risks
- Optional: **`youtube-format-playbooks`** after diagnosis when user approves playbook

## Workflow

1. State format diagnosis: primary/hybrid formats, viewer intent, promise, density, risks.
2. Recommend playbook combination per section when hybrid.
3. Write from [`docs/templates/review/format-diagnosis.md`](../../../docs/templates/review/format-diagnosis.md) → `<rawDir>/edit/review/format-diagnosis.md`.

## Handoff

- [`trim.md`](trim.md) / [`pipeline.md`](pipeline.md) — after user approves diagnosis
- [`guidelines.md`](guidelines.md) — rule lookup during edit

## Related

- Retention (post-structure): [`retention.md`](retention.md)
- AGENTS.md format diagnosis rules
