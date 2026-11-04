# BL-021: Optional talking-head camera treatment

**Status:** Research proposal, not implemented or scheduled.
**Priority recommendation:** After the first BL-020 review slice.
**Surface:** Existing talking-head/motion workflow with an explicit camera choice.
**Source:** [Comparison and camera findings](../../docs/fluxo-de-edicao-comparison.md).

## Outcome

Offer deliberate punch-ins, slow push-ins and pull-backs, plus overlay-aware
reframing. Keep a no-camera treatment. Existing Shorts fixed punch windows and
beat-edit recipes are partial prior art, not this complete capability.

## First slice and acceptance targets

- Resolve the actual format, selected direction, geometry, source/output
  resolution and supported render route. Do not infer opt-in from "talking head".
- Propose numbered moves tied to stable cues, exact cut/word anchors, intent,
  duration, scale/position and easing. Keep timing with canonical BMap authority.
- Render directly from fingerprinted original footage. Compose from the actual
  preceding transform, handle overlaps explicitly and prove forward/backward
  seeks produce the same state.
- Clamp crops to source margins; preserve headroom, captions, products and
  evidence. A pull-back returns to the source framing. Apply current fidelity
  policy and disclose crop/resampling quality limits.
- Plan presenter placement together with overlays. Skip hidden motion under
  full-frame inserts; do not shift the picture for a reserved caption band.
- Support per-ID revisions and contextual proof review; invalidate dependent
  animation, mix/composite evidence and approvals through existing services.
- Test discontinuities, overlaps, cut edges, source changes, blank borders and
  reduced-motion/no-camera choices before broad application.

Face anchoring is a later, explicitly supported slice: cache source-bound
detection, smooth positions, expose confidence, and stop/review on lost or
ambiguous faces. No new detector dependency is required merely to plan zooms.
Never impose alternating zoom on every cut, continuous drift or automatic SFX.
BL-017 editor keyframe export is separate acceptance work.
