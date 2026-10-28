# Animation Delivery Specifications

**Platform-reference review date**: 2026-07-19

**Local code-drawn contract update**: 2026-10-26

Use current YouTube and selected-engine documentation before every final delivery. Do
not hardcode stale bitrate or platform assumptions.

## Source Links

- YouTube upload encoding: https://support.google.com/youtube/answer/1722171
- YouTube altered or synthetic content disclosure: https://support.google.com/youtube/answer/14328491
- YouTube reused content: https://support.google.com/youtube/answer/1311392
- HyperFrames documentation: https://hyperframes.heygen.com/introduction
- Remotion documentation: https://www.remotion.dev/docs

## Project Targets

| Field | Requirement |
|---|---|
| Aspect ratio | TBD: 16:9, 9:16, 1:1, 4:5, or custom |
| Resolution | TBD by platform and project |
| Frame rate | Match source/sequence or documented delivery target |
| Codec/container | TBD by master type and platform |
| Alpha workflow | Engine-specific verified source contract; code-drawn uses FFV1/BGRA Matroska, then the declared final composite/export |
| Color assumptions | SDR BT.709 unless project documents otherwise |
| Audio | See `docs/audio-delivery-specifications.md` |
| Captions | Must remain readable and matched to final audio when required |

## Code-drawn source and delivery boundary

For the advanced code-drawn route, the native generated asset is silent lossless
FFV1/BGRA in Matroska, with the declared dimensions, rational frame rate, exact
frame count and verified opaque/alpha behavior. It is a source graphic, not a
delivery master. Test decoded alpha over contrasting backgrounds, then inspect
the actual canonical composite for color, edges, placement, phase and captions.

Keep composition/source, original input lock, local fonts/assets/dependencies,
licenses, actual browser/driver/generator identity and the generated receipt.
A canonical render must admit current inputs and reconstruct original picture/
audio through a supported native graph; otherwise report a capability blocker.
The existing final encode/audio contract owns the delivered master.
See the [portable QC/delivery guide](../agent-skills/avo-pipeline/references/code-drawn/qc-delivery.md).

Use first/final encoded samples, dense/reveal states, relevant transition strips
and phone-size checks. Frame N-1 is the final sample; time N/rate is the excluded
endpoint. Re-layout only requested 16:9, 9:16 or 1:1 variants, and check loops
only when requested. Candidate hashes and dependency locks bind findings and
rechecks; scores or elapsed time cannot create approval.

## File Naming

Use immutable animation versions:

```text
project-animation-v001-board
project-animation-v002-layout
project-animation-v003-motion-pass
project-animation-v004-review
project-animation-v005-render-candidate
project-animation-v006-master
```

Never use `final-final`, overwrite approved review exports, or detach a render
from its source revision/snapshot.

## Snapshot Requirements

Capture or inspect important frames:

- First frame.
- Title/hook frame.
- Dense information frame.
- Every major reveal.
- Every transition family.
- Data/map/document/UI evidence frames.
- Caption-risk frames.
- Flashing/high-intensity frames.
- Final frame.

## Export QC

- Correct aspect ratio, resolution, frame rate, codec/container, alpha, color,
  and audio assumptions.
- No missing fonts/assets, unexpected transparency, black/white flash frames,
  flicker, crop/stretch, bad masks, or broken nested compositions.
- Motion is deterministic, seekable, and reproducible enough for the delivery
  risk.
- Text and captions are readable and on screen long enough.
- Data, maps, documents, UI, product visuals, and evidence remain accurate.
- No unsafe flashing or excessive motion.
- Rights, attribution, reused-content, and AI/synthetic disclosure records are
  complete.

## Delivery Manifest

For each delivered animation, record:

- Editable source revision/snapshot, composition manifest, original input lock and retained dependency closure.
- Actual engine/route, generator/driver/browser identity and relevant dependency versions/hashes.
- Render command/settings.
- Output file path.
- Duration, resolution, frame rate, codec/container, alpha, audio status.
- Snapshot/check locations.
- Exact candidate SHA-256/dependency-lock identity, timestamped QC findings/rechecks, current review/approval identity and status.
- Rights/source-log status.
- Actual native `edit/delivery-manifest.json` path/hash/state when present. Markdown
  notes project that record and cannot create approval or fill absent evidence.
