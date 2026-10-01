# Watch long-form review reference

## Step/state mapping

**Durable state:** capability snapshot, VisionReviewPlan, fingerprinted raw review artifacts, and the current candidate-bound `kind="watch"` evidence record

**Approval or input gate:** Pause for any model/context/coverage blocker or exact human-review question; report the required endpoint fix, artifact, or disposition.

**Stop when:** Model mismatch, failed probe, unknown unbounded context, mandatory coverage hole, stale review contract, exhausted bounded retries, or unresolved human judgment

**Valid next commands:** the active proof checkpoint command after current Watch evidence passes

## Preconditions

- Exact candidate and transcript fingerprints exist.
- Proof plan, regression contract, required windows, section diagnosis, terms/names, and Watch policy are immutable for the run.
- The endpoint pin names one OpenAI-compatible endpoint and one served model.

## Model preflight

Persist a capability snapshot from a live image request. It binds configured and served identity, vision support, effective runtime context or an explicit conservative limit, output/image limits, visual estimator version, device, concurrency, VRAM ceiling, operator-managed lifecycle, request/response hashes, and probe time. A name mismatch, failed probe, missing vision, or unknown unbounded context blocks review.

Qwen3.5-4B is a local opt-in profile: reuse the already served model with concurrency one inside the declared 7 GB VRAM policy. Do not load Bonsai, start a second model, stop the server, or substitute another endpoint. CPU transcription may coexist only when CPU/RAM/VRAM/I/O preflight allows it; GPU-heavy stages otherwise serialize.

## Context budgeting

For each pass, subtract instruction, rubric/schema, transcript slice, carry-forward, response reserve, and safety tokens from the probed effective context. Divide the remainder by the active detail/resolution estimator cost. The frame ceiling is the minimum of that result, backend image limit, configured safety ceiling, and frames actually required after deterministic deduplication. Record estimator name/version and the requested image policy.

## Layered coverage

1. Deterministic: sequential decode, moving-media variation, exact transcript/protected speech, waveform/tactile events, flash safety, output profile, and section pacing metrics.
2. Sparse overview: first/final regions, every section boundary, representative evidence per section, story and payoff checkpoints.
3. Dense risks: changed/historical joins, overlay entry-hold-exit, captions, privacy, gameplay UI, tactile source audio, moving inserts, transitions, and changed pacing.
4. Repair/comparison: only unresolved findings or explicit comparison requests; prior proofs remain comparison-only.

Record requested, decoded, failed, and observed samples separately. Merge actual inspected and deterministic ranges, report partial ranges and maximum gaps, and list every mandatory coverage hole. `full` describes requested program scope only; it never means every second was viewed.

## Section pacing rubric

Every section supplies format role, purpose, payoff, target density, protected pauses, risk classes, and deterministic metrics such as shot duration, speech density, silence, repetition, section duration, and visual-change cadence. Dense teasers, conversational bodies, gameplay explanations, lifestyle detours, payoffs, and reflective conclusions are judged against their own purpose. Protect complete speech, tactile source sound, comedy timing, emotional pauses, and gameplay/cutscene payoff.

## Findings and evidence fusion

Findings require temporal ranges and fingerprinted evidence references. Distinguish direct visual observation, transcript evidence, deterministic measurement, and editorial inference. Merge semantically identical overlapping findings and their references. Preserve conflicting observations as contradictions. Corroborated blocking findings fail; unresolved material uncertainty needs human judgment; missing/invalid required passes block.

Fuse Watch observations with sequential decode, movement, transcript, waveform, flash, and pacing evidence. Conflicts and low-confidence/masked events generate exact visual or listening windows; the model does not decide ambiguous privacy, identity, rights, factual truth, disclosure, or creator intent.

## Retries and freshness

Retries are bounded and ordered: remove redundant frames, reduce supported detail, shorten transcript handles, then split a window without dropping mandatory endpoints. Never change model, endpoint, capability snapshot, candidate index, or criteria during retry.

The review-contract hash binds candidate and dependencies, policy, coverage plan, required windows, capability identity, prompt, transcript, terms/names, adapter/tool, and estimator. Any change makes evidence stale. Raw stdout/stderr, provider responses, and frame bundles remain fingerprinted raw artifacts; canonical evidence stores references only.

## Human package

Present exact identities and status first, then truthful coverage, regressions, chronological findings grouped by section, pacing evidence, speech/tactile/movement/caption/privacy checks, contradictions and false positives, exact human questions, and concise actions tied to finding IDs.
