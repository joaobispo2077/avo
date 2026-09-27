# /avo.thumbnail Command

**Timeline integration:** Consumes

## Workflow guidance

**Workflow steps:** Validate approved candidate and exact moment → Extract immutable candidate → Verify lineage, display geometry, and color record → Ask for selection

**Step state source:** the approved candidate fingerprint, current canonical CMap when program mapping is requested, and the immutable StillExtractionRecord

**Stopping conditions:** Missing or stale fingerprint, ambiguous cut side, anomalous timestamps without an explicit decoded-frame index, HDR without an explicit supported color policy, extraction failure, or required creator selection

**Valid next commands:** `/avo.deliver`

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md). Follow the exact-frame policy in [`thumbnail.md`](../../agent-skills/avo-pipeline/references/thumbnail.md).

## Usage

```text
avo still extract \
  --project <avo.project.json> \
  --purpose thumbnail \
  --candidate <approved-candidate.mp4> \
  --candidate-frame <frame> \
  --candidate-state approved \
  --candidate-sha256 <sha256> \
  [--color-policy <id>] \
  [--width <pixels>] \
  --format png
```

Review/reference stills may instead request an exact raw rational time or canonical program frame. A program request exactly on a cut must add `--side incoming` or `--side outgoing`. VFR input with missing, duplicate, or non-monotonic timestamps requires `--decoded-frame-index`.

## Rules

- Thumbnail bytes come only from an exact fingerprinted `approved-candidate`; an unapproved current candidate is review/reference-only.
- Candidate-derived stills are delivery/reference artifacts and never proof ancestors.
- Output is an immutable, versioned PNG in `<rawDir>/edit/delivery/thumbnails/` with a sibling record under `records/`.
- Rotation and sample-aspect ratio are applied without crop and recorded. Optional scaling is explicit.
- SDR uses the versioned deterministic tagged-sRGB policy. HDR fails closed unless a supported preserve or tone-map policy is explicitly selected; tone mapping is never implicit.
- Temporary alternatives may be cleaned only after their records, fingerprints, and rejection decisions are retained. Accepted still bytes and records are preserved.
- Creator approval is required before a thumbnail candidate is treated as selected or final.

## Shared timeline gateway

The command reads exact approved lineage and writes only the delivery still and its immutable evidence record. It does not mutate the canonical timeline.
