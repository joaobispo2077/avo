# /avo.costs Command

**Timeline integration:** Admin

## Workflow guidance

**Workflow steps:** Resolve video or history scope -> Read recorded usage -> Verify and report costs
**Step state source:** immutable accounting batches and selected cost snapshot
**Stopping conditions:** Ambiguous context, invalid evidence, or verified cost report
**Valid next commands:** /avo.pipeline, /avo.learndown, /avo.cleanup

Read [cost guidance](../../agent-skills/avo-pipeline/references/costs.md) and the shared [step-status contract](../../agent-skills/avo-pipeline/references/step-status.md).

Use the existing runtime: clone `python -m avo.cli costs`; installed engine `avo costs`. Support `--project`, `--history`, `--phase`, `--provider`, `--video-id`, `--trends` and `--json`. `/avo.metrics` is an exact alias.

Cost inspection is local and read-only. Display recorded tokens, per-model/service/phase breakdowns, valuation basis/unit, coverage and cutoff. Missing usage is unknown, not zero. Do not ask the model to estimate its own tokens or infer costs from its currently selected model. Explicit `costs collect` refreshes already bound local sources without model calls. Binding/import/manual reporting are separate mutations and must preserve source provenance.

## Shared timeline gateway

Resolves provider/video context but performs no editorial timeline mutation. Cost evidence is separate from canonical timeline artifact revisions and approvals.
