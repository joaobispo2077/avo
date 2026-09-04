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
