# /avo.metrics Command

**Timeline integration:** Admin

## Workflow guidance

**Workflow steps:** Resolve video or history scope -> Read recorded usage -> Verify and report costs
**Step state source:** immutable accounting batches and selected cost snapshot
**Stopping conditions:** Ambiguous context, invalid evidence, or verified cost report
**Valid next commands:** /avo.pipeline, /avo.learndown, /avo.cleanup

Exact alias of [/avo.costs](costs.md). Follow [cost guidance](../../agent-skills/avo-pipeline/references/costs.md) and [step-status](../../agent-skills/avo-pipeline/references/step-status.md). Use the same recorded facts, filters, coverage and cutoff; do not calculate a second estimate.

## Shared timeline gateway

Resolves provider/video context but performs no editorial timeline mutation. Cost evidence is separate from canonical timeline artifact revisions and approvals.
