# Timed Shorts inserts and source fidelity

Native Shorts requests support `visualInserts` on each candidate: fingerprinted
silent image/video sources, finite output intervals, normalized placement,
contain/cover fitting, attribution and an optional temporary recording region.
Video source intervals must match their output duration. No looping is inferred.
Source media and ancestry are checked before generated HTML is written.

`output.previewLongSide` defaults to 640. Set 1280 for 720×1280 review of a 9:16
source. `output.pixelFormat: yuv420p10le` selects the registered specialized
source-fidelity renderer. Set `frameRateRational` explicitly for NTSC sources.
It supports BT.709 SDR original 10-bit camera sources and timed inserts;
legacy full-duration split insertions fail closed on this path.

The native resolved Shorts plan remains the timing and media authority.
HyperFrames owns seekable captions, cards and source labels, rendering graphics
alpha only. The native FFmpeg compositor owns original camera picture, ordered
source cuts, temporary regions and silent inserts. Browser-decoded camera
picture never enters the source-fidelity output. The sequential timeline
ProofPlan executor is not advertised as supporting this specialized graph.

`defaults.audioTreatment` and `candidate.audioTreatmentOverride` apply the AVO
dialogue EQ and calibrated noise-reduction strength to the selected original
audio stream. Protected output-time windows bypass treatment sample by sample.
Untreated, treated and removed-signal review stems remain lossless. Noise
reduction never runs on gameplay or effects. The native independent PCM mix
places effects at sample-timed offsets and uses measured two-pass loudness.

Each render records original/insert/alpha/audio hashes, the plan and item hashes,
the composition hash and implementation references in `source-fidelity.json`.
Any changed dependency requires reconstruction. Microproof windows use the same
complete graph, with output-only seeking. Probes reject 8-bit, geometry, rational
frame-rate, color and audio contract violations. Low-resolution proofs still
require exact-file review and human approval before source-resolution work.

Validation includes actual FFmpeg 10-bit ramps, alpha compositing, protected PCM
events, independent effects mixing, source-ancestry rejection and native batch
integration. No footage-specific paths or authoring scripts belong in AVO.

Before reusing a 10-bit proof, the native builder checks its artifact hashes,
registered implementation and declared implementation-file hashes. Stale or
invalid evidence becomes dirty with reason `render-implementation-changed`
and requires a new immutable proof revision.

Run `python -m avo.shorts review PLAN --short 01 --device cpu` for serial
exact-file transcription, project-pinned local vision review and physical QC.
Repeat `--short` to select more items, or omit it for the batch. Native review
binds the proof, transcript and dependency hashes; every model response must
have a verified hash and valid scorecard. Automated review never grants human
approval or creates delivery masters.

