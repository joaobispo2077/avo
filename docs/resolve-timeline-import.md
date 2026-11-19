# Import a Resolve timeline export

AVO imports an exported edit without opening Resolve or asking you to inspect
every timeline detail. Supply the OTIO and original media in your provider-bound
footage project. If available, keep the same-named DRT beside the OTIO: AVO reads
its output settings and supported static title data automatically. DRT alone
is a metadata companion, not a replacement for the OTIO edit structure.

The default workflow stages an editable structural draft and returns consolidated
warnings. Supported treatments become canonical operations; unsupported effects
and generators remain retained data. Import readiness and rendering readiness
are separate. Preserving an unknown effect does not certify its appearance.
Activation remains an explicit action with current Sync evidence and an expected
head check; it does not approve a video.

## Automatic import

Use your existing `avo.project.json` and its provider. No mappings or declarations
document is needed for an ordinary local export:

```powershell
python -m avo.cli pipeline run --project "D:/video/avo.project.json" --timeline-import "D:/video/timeline.otio" --actor "editor" --reason "Continue exported edit" --json
```

The pipeline prepares and validates the draft without activating it. The lower
level `timeline-import prepare` command also selects automatic preparation when
no mappings, declarations or repair predecessor is supplied; call
`timeline-import validate` afterward to obtain readiness and warnings.

Automatic preparation resolves exact exported local paths, locks original bytes,
retains track order, placements, gaps, enabled state, and independent audio. It
reads Resolve audio stream ordinals and channel selections, including duplicated
mono channels. Native packet and decoded audio checks verify timing. An exact
2:1 program/source rate selects an explicit nearest-repeat draft policy; this
does not claim that Resolve used optical flow or another unexported method.
Small verified missing 48 kHz audio tails become declared silence without changing
existing samples. No speech cleanup, pacing changes or creative cuts are added.

The paired DRT can supply program dimensions/rate and a narrowly supported plain
static Text+ template with an exact installed font. AVO never executes Fusion or
Lua, downloads fonts, or substitutes an unknown font. Ambiguous, styled or
animated generators remain opaque references. Without DRT canvas settings, a
draft uses the first moving-picture source dimensions and reports that choice
so it can be changed in AVO. A standalone DRT cannot be imported as a timeline.

Complete static Resolve zoom/pan/tilt and integer frame faders can be reconstructed.
Disabled effects are inert; enabled empty parameter lists remain unknown.
Unknown effects and unverified original video clocks produce warnings and block
strict proof rendering, while the structurally valid draft can continue through
normal editing and explicit activation. Transitions, retimes, nested compositions
and unsupported parent trims still block structural import. Missing or prohibited
sources, changed inputs and ambiguous routing also remain blockers.

Normal review, sync, source provenance and creator approval still apply. Optional
reference comparisons can qualify visual fidelity; inspecting the Resolve UI is
not an import prerequisite. Model analysis uses original media and does not
approve or activate the imported edit.

### A first approximation proof

With explicit authorization, a preview can render the supported treatments while
recording every unresolved effect in `importApproximation`. Such a plan must
have `previewOnly: true`; it cannot be promoted to a full proof or master.
Unknown generated sources and unverified picture clocks cannot be waived.
The canonical draft retains all original effect payloads. The preview filename
and its review report must identify the approximation and its limitations.

For recordings with an otherwise exact picture grid, automatic preparation can
declare one to three missing positions immediately before the final packet as
`pictureEndGapFrames`. Native execution holds the preceding source frame at
those verified timestamps. It does not invent missing pictures, alter original
files, or waive timing irregularities elsewhere. New packets use normalizer
2.7.0, and end-gap imports record `placed-end-gap-1.0.0`.

For explicit privacy corrections, an authored CMap revision can add
`layout.privacyMasks` with its canonical `canvasWidth`, `canvasHeight` and
`regions`. Each region has a stable `maskId`, integral `startFrame`,
`endFrameExclusive`, `x`, `y`, `width` and `height`. The interval is measured on
the imported program clock; the rectangle must remain inside its canvas.
These are opaque black covers above every imported picture layer, including
fades. Scaled preview edges round outward. They preserve audio and edit timing,
require a fresh canonical proof, and do not imply that every private field has
been identified. Review the complete affected interval before delivery.

Authored audio placements can optionally combine `gainDb` with
`audioPeakCeilingDbfs` (-12 to -1) for clip-local peak protection. This is never
enabled automatically by import. The limiter compensates lookahead latency and
runs before microproof extraction; it does not process other tracks. Measure the
encoded mix's true peak and review listening quality before delivery.

Late-timeline microproofs keep only the requested picture intersections in
temporary lossless files and composite on the window's local clock. Source
sampling, fades and privacy retain their original clocks, and audio retains
continuous mix history. Original media is still decoded and validated as needed;
this does not introduce approximate seeking or reuse an earlier proof as input.

## Inspect without reading media

Export the timeline using Resolve's timeline export menu and choose OTIO. Keep
the original Resolve project and media unchanged. From an AVO checkout:

```powershell
python -m avo.cli timeline-import inspect --input "C:/exports/timeline.otio" --json
```

The export alone is sufficient. No provider, footage folder or native OTIO
package is required for inspection. The command reads only the export and
prints a report; it does not follow its media references, fetch URLs, initialize
a project, approve content, or write an edit. Optional `--project` reads the
declared provider for context without initializing the project.

For a collection containing several timelines, select the structural pointer:

```powershell
python -m avo.cli timeline-import inspect --input "C:/exports/collection.otio" --timeline "/children/1" --json
```

The report distinguishes inspection success from reconstruction readiness.
All semantic, media and synchronization checks remain `not-checked`, and
activation is unavailable. An unknown content schema is reported as a blocker
for later reconstruction; successful inspection does not certify fidelity or
that Resolve exported every effect or mix decision. Names and notes are data,
never editing instructions, consent, rights or approvals.

Input limits are 64 MiB, nesting depth 128, 100,000 objects and 2,048 characters
per structural pointer. Duplicate keys,
nonfinite numbers, invalid time rates and unsupported root objects produce
structured errors. Detailed lists are bounded with a truncation indicator and
total clip/track/reference counts retained. Truncated names/URLs also set the
indicator and are counted in `summary.scalarTruncations`; numeric time evidence
is not silently shortened. The input and its numeric declarations
remain distinct from a validated frame rate or source/output timing.

Editable import requires an explicit provider, external footage-project
folder, original-media locations, supported semantics, real Sync/N/A evidence
and normal candidate review gates. Resolve renders and previous AVO proofs or
masters are comparison references, never reconstruction sources. Per-video
import records belong under the external project's `edit/`, not this repository.

## Explicit source-only and repair workflow

Install the optional pinned reader in the checkout environment with
`uv sync --extra dev --extra resolve-import`. Use `uv run --extra resolve-import
python -m avo.cli ...` for these commands so the optional dependency remains
selected. A local Windows engine build also passed the packaged reader smoke;
see [runtime qualification](#reconstruction-cleanup-and-runtime-qualification).

The explicit contiguous mode supports one contributing video track, normal-speed cuts and
explicit linked source audio. It requires exported media origins/available
ranges, matching verified frame rates, explicit audio streams/channels and
declared output settings. Gaps, stills, layered picture, independent audio,
parent trims, disabled content, transitions, retimes and effects block this
contiguous mode. Use the opt-in placed mode below for gaps, layers, stills and
independent audio.
Fractional decimal rates require an explicit rational interpretation; AVO never
silently changes `29.97` into `30000/1001`. A successful native parse is not a
fidelity certificate.

Use an existing provider-bound `avo.project.json` whose `rawDir` is the explicit
external footage folder. First inspect the export to obtain its active reference
pointers. A local mappings document associates each active pointer with the
chosen original and routing, for example:

```json
{
  "/tracks/children/0/children/0/media_reference": {
    "path": "D:/originals/take.mkv",
    "identityConfirmed": true,
    "videoStreamIndex": 0,
    "audioSelection": {
      "streamIndex": 1,
      "channels": [0, 1],
      "sourceLayout": "stereo",
      "outputLayout": "stereo"
    }
  }
}
```

`identityConfirmed` records an explicit editor declaration about a replacement
file. Filename equality alone does not establish identity. Explicit mappings
can repair remote reference text to local originals; AVO never fetches the
exported URL. `dual-mono` requires one selected source channel; `stereo` requires
two. Stream indexes refer to FFprobe's absolute stream indexes.

Create a declarations document with the actual output settings. Set
`sourceOnly: true` only after verifying that no omitted treatment needs to be
reconstructed. Unknown or missing treatments must remain blocked.

```json
{
  "sourceOnly": true,
  "output": {
    "width": 1920,
    "height": 1080,
    "frameRate": {"num": 24, "den": 1},
    "audioSampleRate": 48000,
    "channelLayout": "stereo"
  }
}
```

Prepare and validate without selecting a live edit:

```powershell
python -m avo.cli timeline-import prepare --project "D:/video/avo.project.json" --input "D:/exports/timeline.otio" --mappings "D:/video/mappings.json" --declarations "D:/video/declarations.json" --actor "editor" --reason "Continue Resolve edit" --json
python -m avo.cli timeline-import validate --project "D:/video/avo.project.json" --import-id "<returned importId>" --json
```

Preparation preserves the exact export bytes and creates no canonical heads.
Validation returns scoped blockers or `awaiting-sync`. Use the existing Sync
workflow with genuine evidence and an explicit decision for the exact proposed
sources. This first subset accepts approved N/A for the linked muxed source
clock; importing cannot manufacture that approval. Validate again afterward.

Only a `ready-to-activate` result can be explicitly selected:

```powershell
python -m avo.cli timeline-import activate --project "D:/video/avo.project.json" --import-id "<importId>" --validation-hash "<returned validationHash>" --expected-head empty --actor "editor" --reason "Select imported draft" --json
python -m avo.cli timeline-import status --project "D:/video/avo.project.json" --json
python -m avo.cli pipeline status --project "D:/video/avo.project.json" --json
```

Activation checks the exact proposal, original bytes, Sync decision, target head
and project/provider configuration. Shared timeline writes serialize the commit.
An interrupted activation blocks ordinary editing/rendering until the same
activation is retried and reconciled. An identical retry creates no duplicate
revision. Failed pre-commit operations leave the prior edit usable; committed
operations remain guarded until recovery is coherent. Relinking always requires
an explicit identity choice.

The imported CMap is the active editable truth. Normal pipeline continuation
keeps it and its source-audio preservation policy; requested canonical trims
retain unaffected occurrences. Cut proofs use exact source sample trims with no
automatic fades, restoration, normalization, gain or ducking. Long originals
currently require audio decoding from their origin for sample-exact trims.
Normal candidate transcript, Watch, listening, QC and creator review gates
still apply. BMap/finishing cannot inherit imported approvals.

Qualification uses synthetic FFV1/PCM originals: exact decoded frame/sample
comparisons, a scoped one-frame trim, restart, stale-proposal/source/config
rejection and before/after-commit interruption recovery. Real-export fidelity qualification and actual creator reviews remain separate
gates.

## Placed-layout trial

Add `"layoutMode": "placed"` to the same declarations document to preserve
explicit gaps, repeated clip occurrences, stacked picture, still holds and
independent audio tracks. This model is separate from concatenated CMaps;
it cannot be flattened through the legacy EDL or automated cutting routes.
Scoped edits address a specific placement ID and retain other placements.

Placed output currently requires 48 kHz stereo and verified moving-picture
rates matching the declared output rate. Known non-square source pixels,
transitions, parent trims, nesting, retimes and unsupported effects block.
Video-track order controls composition; upper gaps reveal lower picture,
and uncovered program picture is black. Disabled content remains recorded.
Mute applies to audio; picture visibility uses its enabled state.

Picture references require `videoStreamIndex`. Independent audio references
require `audioSelection` with explicit stream/channels/layout, as in the earlier
example; muxed picture audio is not added automatically. Audio mappings may
declare `gainDb` and `muted`. These are hash-bound editor declarations, not
facts inferred from Resolve metadata. Intentional audio gaps are silent; overlaps
mix without automatic normalization, fades, restoration or ducking.

For a post-cut voice/game balance change, keep the approved CMap and BMap and
author a new Tracks revision with optional `audioTracks.sourceMixAdjustments`.
Each adjustment requires `placementId`, `sourceId`, `sourceSha256`, `streamIndex`,
`channels`, and `gainDeltaDb`; `peakCeilingDeltaDb` can shift an existing source
ceiling. These controls change the existing imported source node, without
adding a second copy of its audio. Unknown, disabled, duplicate or mismatched
targets fail before rendering. Non-cut ProofPlans apply the adjustment exactly
once and recheck it at preflight; cut-proof rendering keeps the original CMap
mix. Use the native ProofPlan route, since legacy assembly rendering rejects
source-mix adjustments. Changed Tracks still require current Animation and
generated-asset dependency bindings before a composite proof.

For a static original image, add `"mediaKind": "still"` to that reference's
mapping. Admission verifies a supported single-frame image and uses literal
filenames, including names containing `%d`. Animated images, renamed video,
sequences and unverified still content block. A static placement holds the
verified first image frame for the exported program interval; the original
virtual source trim remains retained in the export packet.

If the export omits a media origin, supply a scoped declaration such as
`"mediaOrigins": {"/tracks/children/0/children/0/media_reference": {"value": "0", "rate": "24"}}`.
Use the actual original-media origin; zero is never assumed. Decimal frame
rates also require an exact `rateInterpretations` entry, for example
`"29.97": "30000/1001"`.

Preparation uses interpreter version 2.0.0. Reprepare older staged packets
to obtain a new interpretation identity; existing canonical imported edits
remain renderable. Explicit expected-head selection and normal review gates
still apply, including re-import into an existing edit as described below.
Synthetic native tests qualify decoded source reconstruction; an actual Resolve
handoff and creator review remain separate empirical checks.

## Relink moved or missing originals

Repeat `--media-root` during preparation to authorize specific local folders
for candidate searches. Validation searches only those folders, within bounded
entry/candidate limits. It excludes derived edit files and directory-link escapes.
It does not search neighboring folders or fetch network references.

`mediaMappings` reports each active reference's status and filename-only
candidates, including their current byte fingerprints and probed properties.
Even one filename match needs an explicit choice. Two matching filenames remain
ambiguous. A fingerprint verifies selected bytes; it does not establish that
they are the original the editor intended.

Copy the chosen path/fingerprint into that reference's mapping, supply its actual
stream/channel selection and set `identityConfirmed: true` after checking the
original. Prepare a repaired packet using the prior import ID:

```powershell
python -m avo.cli timeline-import prepare --project "D:/video/avo.project.json" --input "D:/exports/timeline.otio" --supersedes-import-id "<prior importId>" --mappings "D:/video/repaired-mappings.json" --actor "editor" --reason "Relink moved originals" --json
```

This explicit repair requires the same exact export and selected timeline.
It inherits omitted mappings, declarations and media roots, overlays supplied
per-reference mappings, and creates a new hash-bound packet. The previous packet
and active edit remain intact. All originals are revalidated; previous validation
or approval is never inherited. Validate the returned new import ID before any
activation choice. Probe failures, incompatible streams, missing files and changed
selected bytes return scoped blockers with repair guidance.

A path-only repair keeps the prior stream/channel choices. Once a predecessor
has verified an original, its byte identity remains locked in inherited mappings,
including references previously resolved directly from the export. Changed bytes
require an explicit new fingerprint selection and a fresh validation; repairing
another reference cannot silently accept those changes.

## Fidelity findings and retained evidence

Each content element has a stable export-scoped identity, a disposition and an
evidence origin. Names, marker text and notes remain reference data. Instructions
inside an export cannot approve Sync, rights, editing, rendering or publication.
Unknown treatments, transitions, retimes, nesting and omitted treatments remain
blocking. Acknowledging a warning, setting `sourceOnly`, or adding a force field
cannot remove a fidelity blocker. Supply a separately revised export when the
editor has intentionally changed the edit.

Output and treatment declarations are bound to the exact staged export and
proposal. A supplied `exportSha256` must match. Declared media origins must name
active references and agree with exported origins. Missing-origin declarations
are supported by the placed model; the contiguous trial still requires exported
available ranges. Exported offsets never count as approval of audio sync.

Moving-picture admission verifies the complete packet timestamp grid against
the selected original's fingerprint. Matching nominal and average frame-rate
headers alone are insufficient. Requested ranges must fit the verified
presented frame count, even when container duration extends beyond the final
frame. The bounded scan supports up to one million
packets, 64 MiB of timing output and 60 seconds of execution; an incomplete,
irregular or over-limit scan blocks reconstruction. Fractional container ticks
and reordered B-frame packets are checked on the exact presentation grid.
Long-source throughput has not been qualified.

Rendering verifies the immutable activation, ready validation, proposal and
original-export chain, while allowing later canonical trims. Keep these records
with the project. A staged proposal or fabricated origin reference cannot select
an edit. Known proof, preview, proxy, master and delivery bytes remain prohibited
as originals after a rename or move; retained materialization records preserve
their fingerprints even after output cleanup.

Reports distinguish checks that failed from checks that were never performed.
JSON output is limited to 16 MiB. Large responses compact duplicated display
details while retaining readiness, identities, hashes, evidence references and
complete counts; explicit truncation flags identify omitted detail. The retained
packet remains the full evidence source. A successful draft activation is never
creative approval or publication permission.

## Provider pipeline handoff

Use the existing provider-bound project and the same mapping/declaration files:

```powershell
python -m avo.cli pipeline run --project "D:/video/avo.project.json" --timeline-import "D:/exports/timeline.otio" --import-media-root "D:/originals" --import-mappings "D:/video/mappings.json" --import-declarations "D:/video/import-settings.json" --actor "editor" --reason "Continue Resolve edit"
```

This convenience route prepares and validates; it returns the import ID, readiness,
scoped findings and next action. An awaiting-sync or blocked result exits 3 with
its report intact. It does not initialize a fresh edit, choose an animation
engine, or activate a draft. Ordinary pipeline run/status/resume preserves an
already selected import and its recorded engine. Provider defaults guide later
requested work; imported canvas, audio, placement and pacing stay canonical.

## Re-import and return to prior content

Prepare the newer standalone export with the current project and explicit source
choices, then validate it. Review `activeEditDiff` and the exact
`validation.locks.expectedHeadHash`. Existing AVO edits remain selected until an
explicit activation uses that returned hash and the exact validation hash:

```powershell
python -m avo.cli timeline-import activate --project "D:/video/avo.project.json" --import-id "<new importId>" --validation-hash "<validationHash>" --expected-head "<expectedHeadHash>" --actor "editor" --reason "Select reviewed Resolve revision" --json
python -m avo.cli timeline-import rollback --project "D:/video/avo.project.json" --activation-id "<replacement activation.operationId>" --expected-head "<current CMap sha256>" --actor "editor" --reason "Return prior content" --json
```

Return reuses the recorded pre-replacement content through a new canonical
revision. It requires current verified originals and approved Sync/N/A for those
originals. Both histories remain, and old cut/candidate approvals remain historical.
An activation into an empty target has no previous edit to return to; return
never deletes a canonical head. No automatic merge or reverse Resolve export is
performed.

After an interruption, inspect status and retry the exact recorded activation
(import ID, validation hash, expected head) or return (activation ID, expected
head). A completed retry creates no duplicate selection and cannot reset later
requested edits. Restore reported changed sources/evidence before recovery. An
unreadable recovery marker blocks selection instead of being overwritten.

## Reconstruction, cleanup and runtime qualification

Canonical reconstruction retains each referenced historical import's exact
export, current packet refs, validated proposal, activation/result and return
journals, including linked repair predecessors. Cleanup preserves that exact
closure; unrelated staged packets are disposable. Required evidence that is
missing, changed, aliased or beyond bounded retention limits blocks cleanup.
External originals remain fingerprinted references, outside the copied bundle
and outside edit-only deletion scope. Their declared files must remain available.

The checkout reader and a local Windows x64 PyInstaller build are qualified. The
packaged smoke verifies inspection, pinned OpenTimelineIO 0.18.1, public staged
validation, disabled hostile plugins and bundled license/notice files without
fetching media. Other frozen platforms and existing downloaded releases are not
certified by that local check. Linux/macOS build and smoke routes use the same
service but require their own platform runs.

Synthetic tests cover exact native frames/PCM, placed layers/gaps/stills/audio,
twelve native recovery exercises, source changes, re-import/return, two-provider
isolation and reconstruction/cleanup. Real-export fidelity qualification and creator
reviews remain separate gates; successful parsing is not evidence of omitted effects.
# Explicit picture sampling

A moving-picture mapping in `layoutMode: "placed"` may explicitly declare
`"pictureSampling": "repeat-2x"` when each native source frame should appear
twice in the program. For example, a verified 30 fps original can be placed in
a declared 60 fps program without retiming its source interval. In this strict route, this is an
explicit reconstruction choice. Automatic import instead records the nearest-repeat
draft policy described above; neither path claims to infer Resolve optical flow
or another unexported interpolation mode.

Admission still verifies the complete native packet clock, source fingerprints,
native-frame trim boundaries and exact output extent. Rendering preserves the
audio graph and uses the same sampling operation in microproof and full proof.
Unknown modes, fractional native trims and implicit frame-rate conversion fail.
The field is invalid for stills, audio, and contiguous-mode imports.

New packets use normalizer 2.6.2 and sampling drafts record
`placed-sampling-1.0.0`; prior canonical histories retain their original version.

## Explicit treatment reconstruction

Placed imports may declare `sourceOnly: false` together with
`reconstructionMode: "declared-treatments"`. Each treatment needs explicit,
scoped data; this mode does not infer defaults or waive unsupported findings.

- `pictureTransform` declares canvas dimensions and the scaled picture rectangle
  (`x`, `y`, `width`, `height`). `pictureFade` declares program-frame alpha fades
  (`inFrames`, `outFrames`). The full proof and microproof use the same operation.
- `audioTailSilenceSamples` records an exact missing tail at 48 kHz. Admission
  counts decoded native samples against the locked source and checks that the
  declaration exactly fills the exported interval. Only the missing tail becomes
  silence; existing source samples and program placement remain intact.
- `generatedTitles` identifies active generated references. Each requires an
  explicit media origin, an original authorial file, a pinned font file, and
  bounded static title data: text, canvas dimensions, position, font size, RGBA
  color, and center or top-left anchor. Both files participate in proof input
  locks. Fusion/Lua payloads are never executed. This supports declared static
  text, not arbitrary Text+ typography, animation, shading, or font collections.
- Explicitly disabled Resolve `Effect.1` entries remain inert `inactiveEffects`
  reference records. Enabled or unknown-state effects still block. Empty
  parameter arrays never establish identity. Effects on parent compositions and
  retiming remain unsupported.

Treatment and title drafts record `placed-treatments-1.0.0` and
`placed-title-1.0.0` respectively. Audio-tail-only drafts record
`placed-audio-tail-1.0.0`. Reprepare older staged packets after a normalizer
upgrade; immutable packets and prior canonical history are not rewritten.

These capabilities are covered by synthetic frame, sample, and admission tests.
Faithful rendering still requires supported retained treatments, current source
fingerprints, sync review, reference qualification where needed, and creator
approval. Automatic drafts use `placed-export-driven-1.0.0`; explicit strict
imports retain the historical capability contracts described above.
