# /avo.thumbnail reference

## Step/state mapping

**Durable state:** the consumed approved artifact, delivery-manifest.json when present, and the observed result

**Workflow steps:** Validate thumbnail prerequisites → Run thumbnail → Verify and report the thumbnail result

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing required input, a failed or stale gate, a required human decision, or verified thumbnail completion

**Valid next commands:** /avo.deliver

Thumbnail candidate stills from approved master (v1: ffmpeg frame extract + checklist).

## Preconditions

- [ ] `provider` + `rawDir` declared
- [ ] Approved master under `edit/masters/` or documented final path
- [ ] Load `providers/<provider>/DESIGN.md` when present for brand/safe-zone guidance

## Parse args

| Arg | Required | Notes |
| --- | -------- | ----- |
| `Provider` | yes | Resolves provider brand assets |
| `rawDir` | yes | Workflow root |
| `Footage:` | optional | Master path; infer latest approved if omitted |
| `--count N` | optional | Default ≥3 frames at distinct timestamps |

## Workflow

1. `ffprobe` master duration; select diverse timestamps (avoid mid-blink, heavy motion blur when possible).
2. Extract stills via ffmpeg to `<rawDir>/edit/delivery/thumbnails/` with versioned names.
3. Apply safe-zone checklist:
   - [ ] Readable at mobile and TV preview sizes
   - [ ] High contrast; faces/products/evidence not cropped awkwardly
   - [ ] **No misleading text** over evidence, faces, or UI that changes meaning
   - [ ] Title/thumbnail promise alignment (truthful, not clickbait fabrication)
4. Optional text overlay **brief** only in v1 — no mandatory HyperFrames composition.
5. **User approval** before marking candidates final in delivery manifest.

## Forbidden

- Fabricated reactions, products, or scenes not in master
- Text that contradicts program content or implies events not shown

## Related

- Provider design: `providers/<name>/DESIGN.md`
- Deliver manifest: [`docs/templates/delivery/delivery-manifest.md`](../../../docs/templates/delivery/delivery-manifest.md)
- Chapters (upload prep): [`chapters.md`](chapters.md)
