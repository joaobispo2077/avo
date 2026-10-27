# Audio and synchronization for code-drawn motion

Code-drawn capture produces a **silent graphic asset**. Narration, source sound,
music and effects remain under AVO's existing audio workflow. Any capable agent
may prepare drawing source and inspect results; model identity does not establish
audio quality or approval.

## Decide the role of sound

Record the format, viewer intent, scene purpose, source limitations and whether
the piece is speech-led, music-led, sound-led or deliberately silent. Use the
actual provider's design and audio policy. Silence and an unchanged source mix
are valid choices; animation does not require music, synthesized effects or a hit
on every movement.

For speech-led work, intelligibility and meaning lead. Align reveals and reading
holds to the final spoken meaning; preserve complete words, expressive pauses,
critical product/game sound and the creator's tone. Keep captions readable and
synchronized. Do not fabricate a quote, performance or endorsement through a
voice, sound edit or misleading cue.

Use [sound](../sound.md) for mix/restoration decisions,
[sync](../sync.md) for source synchronization and
[audio QC](../audio-qc.md) for actual delivery measurement. This guide adds the
drawing boundary; it does not create a parallel mix or audio approval.

## Preserve canonical timing and audio

In a footage pipeline, CMap/BMap own editorial/cue timing, Tracks own resolved
placement and audio choices, and the Sync Map owns source alignment. The drawing
reproduces that declared timing. Retain the approved audio graph, source
fingerprints, sample mapping, levels, automation and channel intent when adding
a graphic. Do not extract audio from an earlier proof/export and use it as a bed.

The browser's capture clock is a frame address, not an audio transport.
Do not use browser playback, an AudioContext, a microphone or a running media
element to decide what frame to draw. Keep the generated FFV1/Matroska asset
silent, including for opaque full-frame graphics. The existing canonical
composition/mix and final encode own program audio. See the
[render contract](render-contract.md).

For standalone motion, declare "silent" or identify the intended external audio
assembly. A successful silent render is not evidence that a finished audio mix,
transcript review or delivery gate exists.

## Measure cues before synchronizing motion

Freeze the exact local narration/music/effect file before timing against it.
Record both the asset-local location and its canonical program mapping.
For each important cue, retain:

| Field | Record |
| --- | --- |
| Source | Local path, SHA-256, role, license and source-log reference |
| Event | Spoken phrase, onset, transient, beat, verified downbeat or section change |
| Location | Actual seconds/samples, relevant source rate and program frame/cue |
| Confidence | Measured, visually/listening-confirmed, or estimated |
| Uncertainty | Timing tolerance, competing event or ambiguous meter/offset |
| Confirmation | Waveform/listening evidence, reviewer and unresolved question |

An onset detector estimates an event; a beat tracker estimates pulse.
Every fourth detected beat does **not** establish a downbeat, bar boundary or
musical meter. Confirm those musically or retain them as uncertain estimates.
Do not invent tempo, exact beat times or sample-accurate sync from listening
alone. A constant tempo grid must not override a real tempo change.

Place measured cues in the existing storyboard/BMap and derive drawing time
from the declared frame rate. Note quantization to frames and preserve the
audio's finer sample timing. Resolve material uncertainty before claiming
precision. Use musical emphasis only where it serves the scene; reading holds
and narration can take priority over a beat.

## Optional narration and synthesis

If requested, record/generate narration or synthesize a sound as an ordinary
asset preparation step. Render it to a local, inspectable audio file first.
Log the generator/tool version, relevant model/prompt or synthesis parameters,
sample rate, channels, duration, seed when applicable, output fingerprint,
rights/consent and disclosure decision. Await the complete file before use.

A synthesized effect may use deterministic oscillators/envelopes and seeded
variation, but it is not a new AVO audio engine. Admit/place the frozen asset
through the existing media/Tracks workflow and mix it there. Avoid live
synthesis inside the drawing page, hidden resampling, nondeterministic buffers,
or repeated regeneration after timings are frozen.

Use existing voiceover review when speech is present. For intentionally silent
or instrumental work, record the actual result and applicable N/A scope.
An expected empty transcript is not permission to fabricate speech or skip
other required review evidence.

## Listen to the actual composite

Check source sync before creative alignment. Then listen/watch the canonical
proof at its beginning, middle, end and every changed or risky cue/join.
Check lips/critical actions, source-sound continuity, drifting offsets,
head/tail pops, clipping, unexpected mutes, channel mapping and speech against
music/effects. Evaluate the actual encoded delivery again when produced.

When a change is graphic-only, confirm the canonical audio mapping/mix remains
unchanged. Where exact preservation is required, use the same graph's lossless
PCM conformance comparison, not a container checksum or a comparison of two
lossy encodes. A timing or mix change needs its owning canonical revision and
fresh applicable review.

Use the documented provider/project loudness and true-peak targets, recording
the measurement method and actual result. No article preset or universal LUFS
number becomes a YouTube requirement. Preserve musical dynamics and source
intent. Use the normal 48 kHz YouTube master policy unless the project documents
an alternative; do not alter source timing to satisfy a visual cue.

Retain cue decisions and new audio assets in SCRIPT.md, ANIMATION-EDITLOG.md and
ANIMATION-SOURCE-LOG.md, plus the project's audio logs when applicable. Finish
with [QC and delivery](qc-delivery.md) and the existing candidate-bound review.
