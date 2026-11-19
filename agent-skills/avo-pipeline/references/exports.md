# /avo.exports reference

Resolve the provider, video and current timeline before preparing an optional
editor handoff. Use the exact selected editor profile. Ask for the intended
range and target only when existing project context leaves them unclear.

Use `avo cli timeline-export status --project FILE` to list target readiness.
Use `prepare`, `inspect-feedback` or `propose-feedback` with `--request FILE`;
each file is an absolute path to a typed local request. Keep the returned
reference and SHA-256 together. See the [editor handoff guide](../../../docs/editor-handoff.md)
for the exact request fields.

Present the validation-only label and affected range for each unsupported
treatment. Compare changes with both the exported example and current timeline.
Show disagreements and ambiguous source occurrences before discussing revisions.
Run accepted changes through the relevant cutting, motion or sound workflow.
