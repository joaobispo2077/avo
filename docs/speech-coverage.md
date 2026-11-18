# Source speech coverage

The existing opt-in cutting analysis returns compact `coverage.speech` summaries
for each analyzed source unit. Each summary names the source, coverage status,
hash, uncertain-range count and immutable `analysisRef`. The corresponding
cutting source-analysis record retains the strict `speechCoverage` document
beside its original words, acoustic observations and model provenance. No
additional mutable timeline or preparation index is created.

Coverage inspection uses already available facts. It does not read source media,
decode audio, start a model, replace a transcript, retry ASR or change a cut.
Source fingerprint, original source range, routed stream/channels, complete
routing hash, Sync, transcript and model/options identities bind each result.
Changed bindings are stale; missing routing, analysis or measured coverage is
unavailable. Missing evidence is never treated as an observed empty result.

The check compares observed acoustic activity with reliable aligned-word ranges
on the original source clock. Gaps remain **possible** speech without reliable
words. Acoustic activity can be noise, music or another false positive; it is
not confirmed speech. Missing alignment cannot certify exact spoken anchors.
Unmeasured portions of a partially observed source unit remain visible too.

`needs-review` identifies unresolved observations. `no-observed-gaps` means only
that the supplied, bound evidence exposed no gap; it does not guarantee a
perfect transcript. Unavailable or stale evidence protects the entire requested
source unit. Other uncertain ranges are rounded outward to original source ticks
for protection, preserving source duration and timing authority.

Retake proposals use those ranges through the existing cutting protection
policy. An otherwise preferred take cannot justify removing a rejected unit that
intersects unresolved coverage. Separate uncertainty can remain flagged while
an unaffected, fully covered take is proposed for normal review. Existing pause
verification and explicit editorial decisions retain their own review flow.
Inspection never grants cut approval or treats recorded speech as instructions.

The source-analysis field is additive: older evidence remains readable and is
reported unavailable when it lacks the new facts. Existing cutting producer
bindings include the coverage implementation and schema, so a changed inspector
cannot silently reuse an earlier verified proposal.

Tests cover omitted takes, false acoustic positives, exact source/routing/Sync
binding, partial/unmeasured ranges, unreliable timing, native-tick protection,
immutable persistence and retake guards. Encoded synthetic fixtures use declared
word labels and native audio verification; they do not qualify actual ASR or
creator listening. Evidence selection and cut approval retain separate gates.

## Selected speech recovery

`avo cli preparation coverage --project <absolute avo.project.json> --request
<absolute coverage.json> --json` reads the exact retained `analysisRef` against
current source, routing and Sync metadata. The request contains
`contractVersion: "1.0.0"`, `operation: "coverage"` and that reference. This read
does not hash source media, decode, inspect model readiness or initialize a
journal. Native and MCP coverage expose the same metadata.

`avo cli preparation recover` uses an explicit typed request with
`operation: "recover"`, a unique `operationId`, `actor`, `reason`, the original
`analysisRef`, source-native `ranges`, an explicitly enabled frozen editing-craft
`selection` and `language`. The direct engine alias is `avo preparation`.
Resolve the existing `speechRecovery` options before creating the request.
Defaults allow one attempt per interval, 30 seconds per interval and 120 seconds
total. Overlapping or oversized selected ranges are rejected before inference;
AVO never clips them silently. Explicit larger validated limits are recorded in
the request. Renaming an operation or changing a model does not reset a started
interval's physical-source attempt budget.

Recovery reuses the selected local transcription model, routed dialogue PCM and
available separately configured alignment. It does not download or switch models.
The crop reduces context to the selected interval, with previous-text conditioning
and ASR VAD filtering disabled through the existing `transcribe_audio` behavior.
The result records actual source offset, measured coverage, source/routing/Sync,
model/runtime, extraction and execution identities. Recovered text remains
reviewable when alignment is missing; it cannot certify exact word anchors or
safe cuts. A pending result is a proposal, not an approved transcript or edit.

The existing cutting journal retains immutable requests, pre-inference claims and
original/recovered alternatives. Exact replay reuses evidence. A crashed claimed
attempt stays interrupted until an explicit new authorized attempt is requested;
it never starts another transcription automatically. Changed original evidence,
source, routing, Sync, model or implementation makes the result stale. Competing
identical operations cannot run the same interval twice.

Reconstruction and fallback inventory verify the journal's bounded exact document
closure, including a durable result whose journal publication was interrupted.
Missing or changed dependencies block reconstruction. Temporary extracted PCM
and unrelated documents are not added to this closure. Human selection between
alternatives and its downstream cutting integration remain implementation work.
