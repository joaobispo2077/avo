# /avo.costs Command

**Timeline integration:** Admin

## Workflow guidance

**Workflow steps:** Resolve video or history scope -> Read recorded usage -> Verify and report costs
**Step state source:** immutable accounting batches and selected cost snapshot
**Stopping conditions:** Ambiguous context, invalid evidence, or verified cost report
**Valid next commands:** /avo.pipeline, /avo.learndown, /avo.cleanup

Read [cost guidance](../../agent-skills/avo-pipeline/references/costs.md) and the shared [step-status contract](../../agent-skills/avo-pipeline/references/step-status.md).

Use the existing runtime: clone `python -m avo.cli costs`; installed engine `avo costs`. Support `--project`, `--history`, `--phase`, `--provider`, `--video-id`, `--trends` and `--json`. `/avo.metrics` is an exact alias.

Cost inspection is local and read-only. Display recorded tokens, per-model/service/phase breakdowns, valuation basis/unit, coverage, cutoff and pending state. Missing usage is unknown, not zero. Do not ask the model to estimate its own tokens or infer historical cost from its selected model. `costs capabilities` separates ten environment rows and bundled native qualification from documentation candidates.

Explicit `costs context --descriptor <file>` registers metadata only. `costs observe --file <packet>` accepts a typed contribution with its own evidence nature and provenance; `costs transition` and `costs estimate` are separate explicit mutations. MCP uses structured descriptors/packets and preserves mutation review; a client file path is not a server file grant. `costs collect` refreshes only authorized attached sources without model calls. Binding/import/manual reporting preserve provenance. A skill alone supplies no host usage; when runtime or qualified native access is missing, use the documented typed/manual/estimate fallback without claiming automatic collection.

For v2 manual evidence from a blank runtime, register context and pass its exact `factId` to `costs report-manual --file <normalized-observations-json> --participation-fact-id <factId> --operation-id <stableId>`. The command freezes a manual-only profile and returns `profileId` for later typed packets. Legacy manual calls without this flag pair are unchanged. MCP exposes the same opt-in as a structured `request` object with `operationId`, `participationFactId` and `observations`, preserving mutation review without a shared client file.

## Shared timeline gateway

Resolves provider/video context but performs no editorial timeline mutation. Cost evidence is separate from canonical timeline artifact revisions and approvals.
