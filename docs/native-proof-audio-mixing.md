# Native proof audio mixing

The default ProofPlan executor can mix finite `music`, `sfx` and `ambience`
audio nodes with its existing source-cut dialogue. A trailer's retained sound
can use a matching `source-audio` event. All ranges remain absolute samples at
48 kHz. AVO owns the timing; generated video and earlier proofs supply no clock.

Each added node requires an exact source trim operation, fingerprinted original,
channel map and matching audio event. The event identifies `audio.nodeId`, has
no visual range, and agrees with the node's source range and impact sample.
Supported additional operations are literal gain, bounded fades, explicitly
declared sidechain ducking and mix. Loops must be expanded into finite nodes by
the canonical author. No arbitrary filter expression is accepted.

The executor still renders source-cut dialogue with its original clip envelopes
and optional authorized noise reduction. The mix adapter reads that ephemeral
lossless lead and adds the declared sources. It emits float PCM before the
executor's one final audio encode. A windowed render uses the same absolute
sample positions as the full graph, including the lead's window origin.

Gain values are literal source amplitude adjustments, not automatic loudness
matching. Measure source levels before choosing relative mix gains; peak/RMS
measurements do not certify intelligibility or replace listening. Restoration,
mix approval, exact-candidate Watch/transcription/QC and creator review remain
separate gates. Unknown operations or stale/forbidden source ancestry fail
before output creation.

Tracks regions can store an explicit rational `timebase`; older regions retain
milliseconds. Containment uses exact rational seconds, preventing numerically
similar ticks in different clocks from hiding a truncated cue. The native
ProofPlan remains the executable authority for its supported frozen graph.

Native dialogue retains its approved raw sample endpoints. When video-frame
quantization changes the required PCM length by at most one frame, the mix
validator represents the native renderer's conformed lead as PCM occupancy.
It still validates original routing and source bounds; it does not rewrite raw
endpoints. The native renderer remains responsible for that bounded conformance.

Finite extractions count decoded native samples before resampling. A conversion
may discard one verified surplus output sample to honor rounded sample endpoints;
missing native samples are rejected before padding. Late cues use lazy exact
silence prefixes rather than program-length delay buffers. One immutable
execution stage can share pixel inspection of a verified generated asset across
multiple ranges; range geometry is checked separately for every operation.
Publication rehashes every distinct original afresh, including within a preview
batch, and retains that batch's final source-change guard.
