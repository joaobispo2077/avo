# BL-017 — `/avo.exports`

**Status:** Wave C (planned)  
**Slash surface:** `/avo.exports`

## Summary

NLE escape hatch: canonical JSON EDL → CMX EDL → FCP XML 1.3 export pack with relink guide.

## Research refinements (2026-11-04)

The [fluxo-de-edicao comparison](../../docs/fluxo-de-edicao-comparison.md) adds
concrete acceptance needs to this existing proposal:

- Export from exact canonical revisions. Preserve original source references,
  rational frame rate/timecode and explicit supported-feature/loss reports.
- Offer a stable role-to-lane convention for camera, screen, full-frame motion,
  overlays, captions, dialogue, source audio, music and SFX. Keep source IDs,
  z-order and channel intent; do not force every project into four video lanes.
- Start with a short fixture opened in the target editor. Verify relinking,
  timing, markers, stereo/channel mapping, alpha, fades and supported keyframes.
- Resolve the format family explicitly: FCP7 `xmeml` and Final Cut Pro `FCPXML`
  are different. The original "FCP XML 1.3" label above is insufficient as an
  implementation contract. The reference's Premiere-specific XML details remain
  hypotheses until a target-version fixture proves them.
- Treat NLE feedback as an explicit import/reconciliation capability. Report
  unsupported retiming, transitions, effects, J/L cuts or unknown media rather
  than silently losing them. Current Resolve/OTIO import work is not proof of
  export or round-trip support.

BL-021 camera keyframes may join the export pack only after the native camera
contract and target-editor representation are both implemented and verified.

## Spec

[`specs/active/avo-capabilities-roadmap/spec.md`](../active/avo-capabilities-roadmap/spec.md) — FR-C2
