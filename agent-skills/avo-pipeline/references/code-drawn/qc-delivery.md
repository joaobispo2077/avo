# Code-drawn QC and delivery

Inspect what was rendered. Author confidence, a screenshot of source, a numeric
self-score or a waiting period cannot establish a passing candidate or human
approval. This workflow is model-neutral and uses the existing AVO review and
delivery authority.

## Check the asset, then its real canonical composite

1. Run native check/snapshot/render with the declared composition and original
   current input lock. Follow the [render contract](render-contract.md); record
   missing or failed checks without filling in a success result.
2. Verify the generated file by decoding it: dimensions, rational frame rate,
   frame count, duration convention, silence, codec/pixel format, color and
   required alpha. FFV1/BGRA in Matroska is the lossless **source asset**, not an
   approved delivery master.
3. In a footage project, require current generated-asset admission and canonical
   ProofPlan/materialization before judging a composite. Use original canonical
   picture/audio and the admitted graphic. A prior proof, proxy, preview, master
   or delivery export is a review reference, never the next proof's picture or
   audio ancestor.
4. Inspect the actual canonical composite after admission: placement, phase,
   clipping, z-order, transitions across cuts, captions, alpha edges and color.
   A standalone generation pass can precede admission; a claimed composite pass
   requires the real downstream output.

If a required native integration or treatment is unavailable, report that
capability blocker. Do not use a hand-built alternate pipeline, silently load
HyperFrames, relabel a standalone render as canonical, or invent receipt fields.

## Build a reviewable visual sample set

Use exact frame indices and the recorded rate. For N frames, sample 0 is the
first image and N-1 the final encoded image; time N/rate is the excluded endpoint.
Inspect the first/final images, each scene's main message and readable hold,
the densest composition, major reveals, changed regions and risky joins.

Include representative stills/contact sheets and relevant transition strips
before/through/after a reveal, morph, camera handoff or cut. Label each image
with its source stage, candidate SHA-256 and frame/time. A strip is a temporal
sample, not proof that every in-between frame was reviewed. Record requested,
decoded and actually inspected ranges, failures and coverage gaps.

For deterministic generation, retain the real check's repeated, reversed or
out-of-order and fresh-session evidence for at least ten representative moments
per supported route, including boundaries. Compare decoded RGBA pixels in the
recorded environment; equal encoded-container hashes alone do not prove
independent seeking. Match browser snapshots against corresponding decoded
asset frames. Compare canonical full/microproof windows with the same frozen
graph and phase, using lossless pixel/PCM conformance where exactness is claimed.

## Accessibility, fidelity and sound

Inspect at final resolution and a small phone-size view. Text must be readable,
high contrast, within safe areas and held long enough for its actual content.
Keep one dominant focus. Verify labels, values, names, units, factual UI and
attribution. Captions stay visible and synchronized over the moving background;
do not shift the film into a reserved caption band. See [captions](../captions.md).

Check essential meaning without relying only on color or movement. Avoid more
than three flashes in a second, rapid full-screen luminance changes, intense
red flashes, prolonged shake and unjustified large-field motion. Document the
appropriate reduced-motion treatment when supported. A template or static
snapshot does not establish flashing safety for a whole sequence.

For transparency, inspect decoded alpha and edges over contrasting light/dark
backgrounds, then inspect those edges over the actual canonical footage.
Check straight/premultiplied-alpha expectations, halos, fringes and unintended
opaque rectangles. Verify declared capture/composite color spaces and actual
delivery metadata; do not fix a mismatch by silently changing the contract.

For sound, follow [audio](audio.md): verify original synchronization, canonical
audio preservation, critical action/dialogue timing, clipping, pops, mapping and
intelligibility on the actual candidate and encoded delivery. Record documented
channel loudness targets and measurements through [audio QC](../audio-qc.md).
Silent graphics still require their actual silent-output verification.

## Findings, fixes and existing review authority

Use the copied REVIEW.md as a human-readable record. Every finding identifies
the exact candidate SHA-256, dependency-lock identity, frame/time range, evidence,
severity, observation versus inference, proposed correction and current status.
After a fix, bind the recheck to the **new** candidate hash, affected source/
canonical revisions, evidence and checked range. Keep unresolved uncertainty
and uncovered regions visible.

The existing ReviewRunner and candidate-bound review.json own automated
deterministic, Watch and transcript evidence. Follow [Watch](../watch.md) for
coverage, model/capability checks, contradictions and stale evidence. Missing
required evidence blocks the checkpoint; silent work uses the real applicable
transcript result/scope, not an invented successful transcript.

Present the existing humanWatch review and exact transcript/candidate package.
Only the user's explicit decision recorded through the existing gate permits
promotion. Do not create a second approval system in REVIEW.md, check a human
box on the user's behalf, promote because a score is high, or treat elapsed
time/silence as approval. A changed candidate or dependency makes affected
evidence and approval stale.

## Requested variants and loops

Adapt only requested outputs. For 16:9, 9:16 and 1:1, re-layout text, graphics,
hierarchy, safe areas and subject/caption/evidence placement to the actual
canvas. Re-wrap text and adjust grouping/scale/holds deliberately; blindly
cropping the horizontal version or squeezing every object is not adaptation.
Preserve factual content, declared timing and audio meaning. If legibility needs
longer holds, revise the owning canonical cues explicitly rather than silently
retiming a variant. Inspect each requested variant's dense/reveal/first/final
states and final encode.

Loop QC applies only when a loop was requested. Inspect the final encoded
sample against the first sample, and reason separately about the mathematical
excluded endpoint. Check motion/position/velocity, state/seed and luminance
continuity plus the actual audio join for pops, gaps or truncated content.
Do not append a duplicate endpoint frame or add a crossfade by default.

## Retain reconstructable source and verify delivery

Keep the editable project and its complete local closure: composition.json,
original input-lock.json, source scripts, fonts, SVG/images/data, optional
drawing-library bytes and licenses, asset/source records and the generated
receipt. Record actual adapter/driver/browser executable identities, versions,
platform/graphics context, seeds, render settings and dependency fingerprints.
Retaining only generated-record JSON or a rendered video cannot reconstruct it.

Fill the copied DELIVERY.md with actual paths, hashes, file properties and
current review/approval references. Use existing ANIMATION-EDITLOG.md and
ANIMATION-SOURCE-LOG.md for decisions, provenance, rights, privacy and applicable
AI/sponsorship disclosures. Preserve immutable versions and the existing
reconstruction/retention policy.

Follow [delivery](../deliver.md) for the final canonical master, exact exported-
file transcript, QC and promotion. The native `edit/delivery-manifest.json`
and its current review/approval state are authoritative; reference its actual
path/hash/state when it exists. The Markdown delivery note is a projection.
Report an absent manifest or pending approval honestly. Do not copy a source
receipt, a successful browser check, placeholder hashes or an agent score into
a claim of delivery approval.

Useful next steps: [troubleshooting](troubleshooting.md) for failed/stale checks,
[rights](../rights.md) for unresolved source permissions, and
[creative direction](creative.md) for meaning or layout repairs.

## Native candidate preview package

`avo cli animation code-drawn-review --candidate <absolute video> --source-receipt <absolute drawing receipt> --output <new absolute directory> --json` decodes the actual candidate into first/final and selected frames, contact sheets and small-display views. Add `--project` for canonical sources. Repeat `--sample-frame` for dense/reveal moments and `--transition start:end-exclusive` for seams; `--loop` adds last-to-first evidence only for a requested loop. A package is sampled visual evidence, not full Watch coverage or creator approval. Preserve its `code-drawn-review.json`, artifact fingerprints, findings/fix/recheck history and exact candidate/source dependency binding. A changed candidate, source/lock/runtime or missing/changed preview requires a fresh package.

For a canonical composite candidate, provide `--project <absolute project> --materialization <absolute native materialization.json>` to `animation code-drawn-review`; it verifies the exact frozen candidate and all used drawing ancestors. Without materialization context the candidate must be the exact generated asset from its single receipt. Use `--render-profile master` when preparing a package for delivery. Native `deliver prepare --motion-review <absolute code-drawn-review.json>` attaches its source/runtime/output metadata while retaining all existing full review and creator gates. Manual existing-master/human-final adoption keeps its existing assembly compatibility limit.

## Native final-fidelity support

The canonical native ProofPlan final-QC path currently verifies progressive 8-bit SDR picture and its supported frozen audio graph. It checks the persisted current materialization, original/generated source closure, microproof gate, actual frame count/rational rate, dimensions, codecs, pixel format, stereo audio and duration against the frozen output contract. Untagged 8-bit source is interpreted as SDR. HDR, wide-gamut, high-bit-depth, interlaced or unsupported mix/profile operations fail explicitly; choose a supported authored contract before rendering. The separate Shorts source-fidelity path has its documented original 10-bit-picture requirements; this native final-QC scope does not replace those rules. Technical fidelity evidence does not grant Watch, listening, readability, rights or creator approval.

Before delivery, review applicable audience and made-for-kids settings, privacy/consent, sponsorship, reused-content and AI disclosure against the current publishing platform guidance; record the decision and source in the project source/review logs. Reference access or generated media does not establish permission.
