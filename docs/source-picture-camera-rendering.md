# Source-picture camera rendering

The renderer candidate applies selected camera paths to verified original picture
before composing independent graphics, captions or credits. It does not change
dialogue timing or sample data. BMap supplies timing, Animation supplies relative
path intent, and Tracks supplies the source-layer identity. Reading or rendering
a path starts no face detector or model.

The shipped capability registry remains unavailable for camera authoring until
the complete profile, recipe/provenance and application controls are qualified.
The implementation is exercised through an isolated qualification candidate in
`tests/integration/test_camera_proof_runtime.py`.

## Numeric and source boundaries

Only schema-validated finite paths and named curves become native filter
expressions. Expressions supplied by requests are rejected. Every operation binds
its source SHA-256, occurrence, layer, geometry, original interval, entry state,
path hash and selected-options hash. The native boundary verifies source bytes,
stream geometry and the constant-rate picture clock before creating output.
Retimed, padded, fractional-frame and out-of-range camera inputs are rejected.
Placed camera decoding retains the shared closed local-container and protocol
policy through staging. A source changed into a playlist after admission is
rejected before it can redirect the decoder to an unadmitted media file.

The baseline uses display coordinates after sample-aspect-ratio correction and
right-angle rotation. The sampler removes the obsolete display matrix after
applying physical orientation. A window evaluates the original path interval,
including across exact source cuts; it never restarts the move at its first frame.
Crop bounds and protected regions are checked for every evaluated frame.

After source geometry is verified, native camera inputs disable autorotation and
consume the selected stream's copied orientation with a zero
[`display_rotation` override](https://github.com/FFmpeg/FFmpeg/blob/n6.1.1/doc/ffmpeg.texi#L841-L851).
The frozen original rotation still drives the physical transform. This prevents
older runtimes from retaining container rotation after the frame-side marker was
removed. Normal proofs and unselected source streams keep their existing path.

The sampler supplies one private replicated row and column, keeps coordinates
bound to the original dimensions, then removes that extension before output
scaling. This preserves boundary samples across runtime versions: FFmpeg 6.1's
[bilinear lookup](https://github.com/FFmpeg/FFmpeg/blob/n6.1.1/libavfilter/vf_geq.c#L103-L114)
clamps coordinates before interpolation. Actual legacy-kernel tests reproduce
the earlier edge loss and verify the corrected identity, boundary and window
pixels without relaxing exact source comparisons.

## Precision and composition

The internal camera sampler uses 16-bit planar RGB. Explicit precision proofs
compose picture and alpha planes before their requested final pixel conversion.
Source framing never transforms independent output-space graphics. Placed full
proofs keep the existing bounded chunk storage and one continuous final encoder;
the byte budget includes eight bytes per 16-bit alpha layer pixel and six bytes
per composed RGB pixel. Partial placed proofs rebuild their private stages from
original sources rather than reusing an unqualified camera-stage cache.

An explicit delivery pixel format currently requires `yuv420p`. Higher-precision
formats require the selected FFV1/PCM conformance route; unsupported delivery
codec/pixel pairs fail before rendering instead of negotiating a lower depth.

Opaque RGB/alpha insertion and alpha removal copy planes. A regular RGB-to-RGBA
conversion was observed changing 16-bit values even at identical size and depth;
the exact-pixel tests caught that conversion before activation.

HDR/wide-gamut input, source-alpha camera sampling, placed privacy masks, camera
sampling/fades and reduced-depth output remain unqualified and fail preflight.
The existing placed admission boundary also requires square source pixels; the
contiguous sampler separately exercises SAR and rotation. No profile is advertised
ready from contract validation alone.

## Validation boundary

Actual encoded fixtures cover 16-bit identity and low-bit detail, independent
audio, full/window seeking, SAR/rotation, fixed graphic layers, cut continuity,
and rejection before output creation. Tests compare decoded pixels and PCM rather
than trusting declared formats. Existing placed, stage-cache and generated-asset
regressions remain required. The specification acceptance ledger records each
observed run and any failures; synthetic fixtures do not establish creator
suitability or approval of a production edit.

Before activation, implementation fingerprints and render recipes must include
the native camera kernel, precision composition, runtime tools, frozen options
and sources. Selected camera controls and map/card states must use the existing
recoverable canonical owners. These remaining tasks do not enable camera moves
or face anchoring by default.
