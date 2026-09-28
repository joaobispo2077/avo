# /avo.watch Command

**Timeline integration:** Evidence

## Workflow guidance

**Workflow steps:** Preflight exact model → Plan bounded coverage → Run layered review → Verify evidence → Present human package
**Step state source:** current candidate, VisionReviewPlan, capability snapshot, and review.json
**Stopping conditions:** Model mismatch, failed vision probe, unknown context without a conservative limit, mandatory coverage hole, stale contract, malformed output after bounded retries, or required human judgment
**Valid next commands:** the active proof checkpoint command after all blockers are resolved

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md). Load the detailed [`watch.md`](../../agent-skills/avo-pipeline/references/watch.md) reference.

## Required behavior

1. Reuse the configured operator-managed OpenAI-compatible endpoint. Verify the exact served model name, live vision response, effective runtime context, output/image limits, and resource policy. Never start, unload, or substitute a model silently.
2. For the local Qwen3.5-4B profile, require concurrency one and the declared 7 GB VRAM ceiling. CPU transcription may share the run only when resource preflight permits it; competing GPU stages serialize.
3. Budget every pass from instructions, rubric/schema, local transcript, carry-forward, response reserve, safety margin, and versioned visual-token estimate. `maxFrames` is a ceiling, not proof that a request fits.
4. Run deterministic checks first, sparse scene-aware coverage across every section, dense risk-window review, then targeted repair/comparison only when required.
5. Judge pacing per declared section format, purpose, payoff, target density, deterministic metrics, and protected pauses. Never impose one universal cut rate.
6. Keep findings structured and evidence-linked. Deduplicate semantic overlaps, retain contradictions, and route ambiguous privacy, identity, rights, factual, speech, tactile, and pacing questions to a human.
7. Retry only within policy: deduplicate redundant frames, reduce detail, reduce transcript handles, then split windows with bounded overlap. Keep the same candidate index, endpoint, model, capability snapshot, and criteria.
8. Report actual requested, decoded, failed, and observed samples. Requested or nominal `full` scope never counts as inspected coverage.
9. Store stdout, stderr, provider responses, and frame bundles as fingerprinted raw artifacts. Canonical evidence stores their references and hashes, not raw payloads.

## Output

Emit one current `kind="watch"` evidence item plus a human-readable package containing exact identities, truthful coverage and holes, regressions, chronological section findings, pacing evidence, contradictions, human questions, and finding-linked actions.

## Shared timeline gateway

Runs through the Evidence command mode. It reads the active immutable candidate and emits candidate-bound review evidence; it does not mutate editorial state or manage the operator's model lifecycle.
