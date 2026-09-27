# Configurable Watch execution and review policy

Watch policy resolves per field from global configuration, provider
`routingOverrides.watch`, video-registry `defaults.watch`, project `watch`, and
one-run `--watch-*` flags. Arrays replace lower scopes. Use `avo review policy`
to inspect the effective values and their sources without running media tools.

The generic defaults inherit AVO's effective transcription model, choose device
`auto`, inspect at most 18 frames, use 8 frames for bounded structured-output
repair, permit two analysis attempts and three tool attempts, and use the
candidate directory. Format, language, acceptance criteria, and risk notes are
omitted from prompts unless declared.

`cpu` is the only value that forces GPU hiding. `auto`, `cuda`, and `cuda:N` do
not inherit a forced-CPU environment. Invalid ranges, path escapes, or a repair
budget greater than the main frame budget fail before the tool runs.

Watch selects the last schema-valid object from an answer, retains every raw
attempt, and distinguishes content findings from uncertainty/refusal, malformed
output, tool errors, and insufficient coverage. Uncertainty and refusal require
human judgment. Tool, malformed, and coverage failures block. None are silently
converted to pass.

The evidence stores the policy hash, sources, generic prompt context, prompt
hash, actual tool/model identity, attempts, and coverage. A policy change makes
earlier evidence stale even if candidate bytes are unchanged.

See [`optional-capabilities.md`](optional-capabilities.md) for every flag,
accepted value, example, artifact effect, and valid next workflow action.

## Current-source audit

Reviewed 2026-09-02. Watch policy contains no platform-named resolution,
bitrate, aspect-ratio, language, format, topic, model, or device assumption.
Platform delivery guidance belongs in an explicitly selected delivery profile,
not in visual-review execution defaults.

## Context-budgeted long-form review

Watch preflight binds the configured and actually served model, live vision
probe, effective context provenance, image/detail limits when available,
adapter/tool versions, and resource policy. A served-model mismatch, missing
vision support, or unknown context without an explicit conservative limit
blocks. The runtime does not substitute another model.

The planner reserves instruction, rubric/schema, section-local transcript,
carry-forward, output, and safety tokens before allocating visual samples. A
fixed frame count is only a ceiling. Small contexts produce more bounded passes
rather than dropping required sections, boundaries, historical risks, caption
checks, privacy windows, tactile actions, or pacing windows. Bounded retry may
reduce frames, detail, transcript, or window span while retaining the same
model, and every retry is recorded.

Sparse passes orient the opening, ending, section boundaries, promise, payoff,
and representative section content. Dense passes cover changed joins and known
risks. Deterministic sequential decode, movement, transcript, waveform, flash,
and pacing checks remain independent evidence. Findings are normalized without
hiding contradictory observations; uncertain privacy or factual judgments route
to exact human-review windows.

Coverage reports requested, decoded, inspected, failed, partial,
deterministic-only, and uninspected ranges plus maximum observed gaps. Sampled
frames are never described as continuously watched footage or as
`reviewedSeconds=duration`. One aggregate Watch record binds the candidate,
dependencies, policy, plan, windows, capability, prompt, transcript, terms,
adapter/tool versions, and estimator identity.

Pacing is judged per declared section purpose, target density, information
load, emotional role, and protected pauses. It is not a universal cut-rate
score. The human package presents chronological findings, contradictions,
coverage limits, regressions, questions, and finding-linked actions.
