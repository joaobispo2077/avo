# BL-024: Source-anchored spoken editing notes

**Status:** Research proposal, not implemented or scheduled.
**Surface:** Optional preparation/transcription and cut-proposal workflow.
**Source:** [Reference comparison](../../docs/fluxo-de-edicao-comparison.md).

## Outcome

Recognize creator-configured phrases delimiting recorded notes, such as an
opening and closing "editing note" phrase. Present a source-anchored note and
route its proposed intent to cuts, assets, motion, camera or sound.

## Acceptance targets

- Require the creator's convention/scope; support declared language and tolerate
  ASR variation without treating arbitrary media speech as agent instructions.
- Record source identity, full delimiter range, verbatim transcript,
  interpretation, target stage and confidence separately.
- Match notes to an explicit neighboring source span. Ambiguous targets,
  missing terminators, quoted phrases and false positives require review.
- Propose exclusion of confirmed recording-note speech through normal CMap
  services; do not delete time or apply the interpreted instruction automatically.
- Retain unresolved notes across resume/rebase and preserve protected content,
  natural performance, current review gates and explicit breath opt-in.
- Test multiple files, repeated/quoted delimiters, transcription errors,
  unterminated notes, revisions and source-to-output rebasing.

Reuse transcript packing, source anchors and native proposal/review services.
No new mutable project-state file or per-video extraction script is implied.
