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
creator listening. Selected ASR recovery, evidence decisions and the dedicated
preparation commands remain separate implementation work.
