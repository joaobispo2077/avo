# /avo.thumbnail reference

## Step/state mapping

**Durable state:** exact candidate/source fingerprint plus the immutable StillExtractionRecord and selected image bytes

**Workflow steps:** Validate lineage → Resolve exact frame → Extract → Verify record/output → Request creator selection

**Approval or input gate:** Stop for a missing fingerprint, ambiguous cut side, timestamp anomaly, unspecified HDR policy, or creator selection.

**Stop when:** Any required lineage/input is missing or stale, extraction or verification fails, or creator selection is required.

**Valid next commands:** `/avo.deliver`

## Preconditions

- `provider`, `rawDir`, and `avo.project.json` resolve to the active footage project.
- A thumbnail request names an approved candidate and its exact SHA-256.
- A raw/program review request resolves through the current valid CMap and verifies the registered source fingerprint.
- Provider `DESIGN.md`, when present, supplies brand and safe-zone guidance after truthful extraction.

## Exact moment inputs

Use exactly one input mode:

| Mode | Required fields | Resolution |
| --- | --- | --- |
| Raw source | `--source-id`, `--source-time-num`, `--source-time-den` | Rational seconds from normalized stream start; decode registered source bytes directly. |
| Program | `--program-frame`, `--frame-rate-num`, `--frame-rate-den` | Resolve through current CMap half-open ranges to source/frame. At a cut, require `--side incoming|outgoing`. |
| Candidate | `--candidate`, `--candidate-frame`, `--candidate-state`, `--candidate-sha256` | Resolve by explicit decoded-frame index against exact candidate bytes. Thumbnail requires state `approved`; current is review/reference-only. |

For ordinary VFR timestamp requests, select the decoded display interval `[PTS,nextPTS)` containing the requested time. An exact PTS boundary selects the incoming frame. Missing, duplicate, or non-monotonic PTS blocks timestamp selection; use an explicitly chosen `--decoded-frame-index` when editorially justified.

## Output and verification

1. Extract one frame without approximate-seek selection or network input.
2. Apply declared display rotation and sample-aspect ratio without crop. Source resolution is the default; `--width` records an explicit derivative.
3. For SDR, use the versioned deterministic conversion and tag the lossless PNG as sRGB. For HDR, require an explicit supported policy: preserve (`hdr-preserve-v1`) or deterministic Hable tone map (`hdr-tone-map-hable-v1`). Never infer a tone map.
4. Write `<video-id>-<purpose>-f<decoded-frame>-vNNN.png` to:
   - thumbnails: `<rawDir>/edit/delivery/thumbnails/`;
   - review/reference: `<rawDir>/edit/review/stills/`.
5. Write the sibling immutable record to `records/<extraction-id>.json`. Verify request, PTS interval/index, boundary side, input/output fingerprints, canonical mapping when available, geometry, color policy/tool version, purpose, and approval state.
6. Check mobile/TV readability, safe zones, truthful promise alignment, and awkward face/product/evidence crops. These design checks do not change which source frame was extracted.
7. Ask the creator to select a candidate. Selection is a human decision; extraction alone does not approve it.

## Admission and cleanup

- Candidate-derived stills are reference/delivery-only and cannot enter any proof graph.
- A raw-derived still may enter a proof only after separate registration as a canonical generated asset with full lineage.
- Never use a proof, preview, proxy, master, or delivery export as an editing ancestor.
- Preserve accepted image bytes and immutable records. Disposable alternatives may be removed only after their record, fingerprint, and rejection/supersession decision are retained under project cleanup policy.

## Forbidden

- Extracting a thumbnail from a current/unapproved candidate.
- Guessing incoming versus outgoing at a cut.
- Timestamp selection across anomalous VFR PTS without an explicit decoded index.
- Implicit HDR tone mapping, undocumented crop/grade/scale, or fabricated reactions, products, text, or scenes.

## Related

- Canonical contract: `specs/006-iteration-aware-proofing/contracts/still-extraction.md`
- Provider design: `providers/<name>/DESIGN.md`
- Delivery manifest: [`docs/templates/delivery/delivery-manifest.md`](../../../docs/templates/delivery/delivery-manifest.md)
