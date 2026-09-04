# /avo.color reference

## Step/state mapping

**Durable state:** pipeline-run.json plus the current canonical timeline revision

**Workflow steps:** Validate color prerequisites → Run color → Verify and report the color result

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing required input, a failed or stale gate, a required human decision, or verified color completion

**Valid next commands:** /avo.deliver

**Visual / color QC stage** — checklist only in v1. Distinct from creative grade during edit ([`grade.md`](grade.md)); confirms evidence and brand integrity before deliver.

## Preconditions

- [ ] Picture lock or approved master export
- [ ] Provider `DESIGN.md` consulted when brand color fidelity matters

## Workflow

1. Spot-check skin tones, product color, UI fidelity, chart/map readability.
2. Flag misleading grade that changes evidence meaning — **FAIL** release-blocking.
3. Write from [`docs/templates/review/color-qc.md`](../../../docs/templates/review/color-qc.md) to `<rawDir>/edit/review/color-qc.md`.

## Handoff

- [`deliver.md`](deliver.md) visual row may link this artifact

## Related

- AGENTS.md visual clarity rules
