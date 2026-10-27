# Code-drawn render contract

Read [setup](setup.md) for the actual native commands and [creative](creative.md) before composing. The executable Canvas/SVG/brush starters come from `code-drawn-scaffold`; keep one source owner rather than copying a second renderer from an article.

The author supplies a complete local drawing at any requested time. AVO validates the source, observes the browser environment, captures integer-addressed frames, and verifies a silent generated asset. The drawing does not own footage cuts, edited-timeline placement, audio mixing or approvals.

## Manifest and local source closure

`composition.json` is authoring input with strict known fields:

| Field | Required meaning |
| --- | --- |
| `schemaVersion` | Exactly `1.0.0`. |
| `compositionId` | Stable identifier for this composition, such as `code-drawn-canvas`; lowercase letter first, then lowercase letters/digits/hyphens, 3-64 characters. |
| `engine` | Exactly `code-drawn`. |
| `drawingRoute` | `canvas`, `svg` or `brush`. |
| `entry` | Local HTML path, also declared in `files`. |
| `files` | Complete nonempty source closure. Each item has `path`, `sha256`, `sizeBytes`, and `role` (`source`, `script`, `style` or `data`). |
| `assets` | Local assets with `id`, `kind`, `path`, `sha256`, `sizeBytes`, `rightsRef`, plus required kind metadata. An empty list is valid. |
| `dependencies` | Local libraries/builds with `name`, `version`, `build`, `path`, `sha256`, `sizeBytes` and `licenseRef`. An empty list is valid. |
| `seed` | Recorded integer or nonempty string controlling all procedural variation; do not silently regenerate it. |
| `sourceRevision` | Immutable source-snapshot identity for this revision. |
| `renderContract` | Exact dimensions, rational rate, frame count, background, alpha, colors and supported sampling. |
| `manifestHash` | AVO canonical document SHA-256 excluding `manifestHash`; this differs from the full manifest file's byte hash. |

All declared input paths use normalized forward slashes relative to the composition directory. Reject absolute paths, backslashes, drive/URL prefixes, traversal, duplicate declarations and symlinks escaping the source root. Declare every imported script, stylesheet, local data file, image, font, library and required license file. A package name or a remote URL is not a fingerprint of the bytes used.

The capture host serves only the declared frozen byte closure under its internal local origin. A relative fetch of the declared local brush script is valid. External HTTP requests, undeclared paths/query variants, sockets, unavailable fonts, and unregistered imports fail. Freeze remote data/screenshots/model outputs into approved local files before final rendering; never fetch fresh results in `seek`.

Font assets use `kind: "font"` and declare `family`, `style` and `weight`. Image/SVG assets use their actual kind and may declare expected positive `width`/`height`. Keep original-source/extraction fingerprints in `sourceRef` when an asset derives from media, and retain its real rights evidence in the source log. Do not label a raw-derived still source-free to avoid canonical ancestry checks.

## Exact frame and output targets

A starter's render contract has this shape; use the approved target values:

```json
{
  "width": 1280,
  "height": 720,
  "frameRate": {"num": 30000, "den": 1001},
  "frameCount": 90,
  "background": {"mode": "transparent"},
  "alphaMode": "straight",
  "captureColorSpace": "srgb",
  "compositeColorSpace": "sdr-bt709",
  "quality": {"spatialSamples": 1, "temporalSamples": 1}
}
```

Dimensions and counts are positive integers. Frame rate is a reduced positive rational, not a floating-point approximation; the scaffold accepts `--fps num/den` and reduces it. The current capture pixel budget is 33,554,432 pixels (`width * height`). Validate targets before allocating a browser surface.

For integer index `i`, require `0 <= i < frameCount` and compute time directly as:

```text
tSeconds = i * frameRate.den / frameRate.num
duration = frameCount * frameRate.den / frameRate.num
lastSample = (frameCount - 1) * frameRate.den / frameRate.num
```

Never accumulate rounded frame intervals, add a frame at `duration`, or confuse the conceptual loop endpoint with the last rendered sample. Snapshot `--frame` takes an integer index. Review the last sample and loop transition deliberately.

Current quality support is exactly one spatial sample and one temporal sample. Other values are unsupported and fail validation. Supersampling, temporal blur and custom shutter windows are not runnable options in this renderer. A spring or easing function does not itself provide motion blur.

For opaque work use `background: {"mode":"opaque","color":"#121212"}` with `alphaMode: "opaque"` and paint that intended explicit color. For an overlay use `background: {"mode":"transparent"}` with `alphaMode: "straight"`; omit a background color and leave transparent regions unpainted. Source CSS and the drawing must agree. A transparent browser screenshot cannot restore alpha after a full-frame opaque fill.

Capture is lossless RGBA PNG in the declared sRGB environment. The generated intermediate is silent FFV1 with BGRA pixels in a `.mkv` Matroska container. Output verification records full range, dimensions, exact rational rate, frame count, silence, exact decoded RGBA round-trip, alpha and controlled contrasting-background checks. It does not turn this drawing into an HDR output or final delivery encode. Preserve the declared `sdr-bt709` composite target through the canonical pipeline and review the actual composite there.

The scaffold substitutes width, height, rate, frame count, background and seed constants into its generated source. The host does not inject changed manifest values into the page. Keep those source constants and the manifest consistent when revising; editing only the manifest does not resize, re-time or reseed an old page. For a new layout/target, scaffold into a fresh destination, adapt its composition deliberately, then fingerprint/seal/check that new source version.

## Drawing-page bridge

The page must expose exactly one visible capture surface `#avo-stage`, at origin `x=0, y=0`, with capture bounds equal to the declared width/height. Keep browser chrome, scroll areas, debug text, preview controls and unrelated DOM outside the picture.

The host sets `window.__AVO_RENDER__ = true` before page scripts run. The page provides:

- `window.avoReady`: a Promise resolving only after initialization and all required local drawing inputs are ready; reject on failure.
- `window.seek(tSeconds)`: a synchronous or async function whose completion means the entire requested visual state is painted and ready to capture. The host awaits it.

Use time as an input, never as evidence that some previous frame happened. Each seek must reconstruct the complete state independently. Reset transforms, paths, alpha, compositing, clips, filters, caches and procedural randomness before drawing. SVG uses explicit time-derived attributes/states; avoid autonomous SMIL/CSS timelines. Do not use wall-clock time, unseeded randomness, preview loops, user-input state, timers or accumulated simulation steps as the final animation clock.

A valid sequence includes seeking a late frame first, returning to frame 0, repeating a frame, reversing through moments and starting a fresh browser session. Seeding once when the process starts is insufficient if later draws consume shared random state. Derive per-object variation from stable recorded identifiers or reconstruct the seeded state for every requested time.

For the brush starter, preserve the fresh isolated standalone library instance and temporary WebGL2 surface per seek. Its private seeded randomness also covers vendor initialization before public seed APIs exist. Flush GPU work, copy into the stable 2D `#avo-stage`, check graphics errors, and release the temporary context. Do not replace this with one persistent mutable brush object without proving independent-seek parity.

## Asset and render readiness

Load every required font before measuring or drawing text. Await the declared faces and `document.fonts.ready`; verify the intended face is loaded and inspect the required glyphs. A fallback font may render readable text while changing layout, so it is not evidence that the required asset succeeded.

Await image load/decode and verify nonzero/declared dimensions before drawing. Report a rejected ready Promise, failed image decode, corrupt font, missing brush bytes, WebGL2 failure or page error as a blocked attempt. A fixed delay or "network idle" alone does not establish readiness.

The host observes declared asset loads and the bridge. The actual page must also await its own initialization and work. Do not catch an asset error and resolve `avoReady` with an empty scene. Use the native `code-drawn-check` rather than declaring a frame ready after a browser preview looks plausible.

Browser capture is silent. Do not play audio/video, synthesize a browser sound bed, or use a previous proof/master as picture or embedded media. Original footage playback, dialogue, music and SFX remain in the canonical graph; [audio guidance](audio.md) covers cue planning.

Check samples ten distributed frame positions, repeats them, reverses them, then compares a fresh session using decoded RGBA hashes and a matching observed environment. Short compositions may repeat the same index among those positions. This detects history dependence at the sampled moments; also inspect important unsampled transitions at final targets.

## Revise source before freezing inputs

Editing HTML, JS, SVG, CSS, data, an asset or a dependency immediately makes its old declared SHA-256/size stale. Editing the manifest also changes its seal. There is currently **no native `refresh` or `reseal` command**.

An advanced agent must have file-editing, byte-count, SHA-256 and matching canonical-JSON capabilities. If its tools cannot compute these correctly, stop source authoring with that concrete capability gap. Do not suppress verification or hand the native renderer a deliberately false manifest.

Use this revision workflow:

1. Preserve the prior immutable source closure, manifest, original input lock, receipt and review state. For a revision, copy the editable source/assets/dependencies into a distinct new source-version directory. Do not carry old output/receipt/lock files into the new editable draft as current evidence.
2. Edit the new draft and set a new `sourceRevision`, keeping `compositionId` stable for the same composition. Add/remove declarations to match its complete actual input closure, including local licenses.
3. For every item in `files`, `assets` and `dependencies`, set `sizeBytes` to the actual byte count and `sha256` to the lowercase SHA-256 hex digest of those exact bytes. Check path containment and preserve metadata/rights references.
4. Compute `manifestHash` from the full parsed manifest with only that top-level field excluded. Use AVO's serialization below; save the resulting manifest. Source-file and manifest seals must agree before native check.
5. Run `code-drawn-check --composition <absolute-new-manifest> --output-lock <absolute-new-lock>`. Review the evidence and snapshots. Render with that original new lock and fresh output paths. Never rewrite an old lock to make changed inputs appear current.

AVO canonical JSON is UTF-8 from Python `json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)`: recursively sorted object keys, no pretty-print whitespace, Unicode retained, and no NaN/Infinity. It is not a hash of the displayed/pretty JSON or a generic `JSON.stringify` result. Numeric serialization must match this definition.

This optional stdlib reference computes a seal for an already prepared **new draft** object. It is an agent-side authoring example, not a dependency of frozen native operations, and does not update a lock or write a file:

```python
import hashlib
import json

def seal_new_manifest(manifest):
    payload = {
        key: value for key, value in manifest.items()
        if key != "manifestHash"
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return {**payload, "manifestHash": hashlib.sha256(canonical).hexdigest()}
```

In a source checkout, `avo.motion.seal_composition(draft)` provides that same document seal and returns a copy. It does not refresh file fingerprints or validate that an authored page is seek-safe; perform the other steps and native check. Frozen agents can use existing file/hash tools that match the definition; do not require users to install external Python or Node just to run the native renderer.

Moving the source may change absolute locators in an input lock. Retain old evidence for its original binding, and check/freeze a new lock in the relocated workspace. A portable project retains its own source/library/assets; portability does not authorize changing an existing locked locator or environment.

## Original input lock and receipt

Check without `--output-lock` validates only. A new `--output-lock` creates a standalone lock; supplying `--input-lock` also verifies the retained lock against current inputs/environment. Render requires `--input-lock`. Snapshot may omit it for draft inspection, but a snapshot without a lock is not frozen provenance.

The lock binds `instanceId`, `bindingMode`, `manifestRef {path,sha256}`, `renderContractHash`, `inputs`/`inputsHash`, generator bytes/version and the observed environment. `inputLockHash` seals the parsed lock excluding itself. In contrast, `inputLockRef.sha256` fingerprints the complete saved lock file bytes, including its seal and formatting. These identities are different and both must be honest.

The original lock is fixed before materialization. The renderer rechecks it during/after work; source, seed, contract, dependency, generator or environment changes stale the attempt. Never observe fresh heads at completion and reseal them into the original lock. A new preference alone is not a source mutation and does not rewrite existing work.

Successful `asset.generated-asset.json` uses AVO's generated-asset record. `parameters.codeDrawn` includes:

| Field | Evidence bound to this output |
| --- | --- |
| `instanceId`, `sourceRevision`, `drawingRoute` | Exact authored instance, immutable source revision and actual drawing route. |
| `manifestRef`, `inputsHash`, `renderContractHash` | Exact source-manifest bytes, input-set identity and render target. |
| `inputLockRef`, `inputLockHash` | The original retained lock's file fingerprint and canonical seal. |
| `captureEvidence` | Independent-seek frame hashes, sampled positions and observed environment. |
| `outputVerification` | Actual decoded dimensions/rate/count/silence/pixel/alpha/color checks. |
| `canonicalInputLock` | Included only for an actual canonical binding; absent in standalone output. |

A receipt is downstream evidence, never source authority or human approval. Standalone success has no fabricated canonical revisions. Only the shared canonical coordinator can supply a verified canonical binding, range and placement from current maps/tracks; the composition does not duplicate those authorities. Passing a hand-written canonical lock or an old standalone receipt is not admission.

The renderer waits for encoder success and verifies decoded pixels before publishing output and its receipt. Existing outputs/receipts are not overwritten. Admission, actual canonical composite QC, ProofPlan/proof reconstruction and review happen in their existing owners after generated-media validation. Follow [QC and delivery](qc-delivery.md) and preserve the original inputs for reconstruction.

## Local assets and explicit ancestry

A newly licensed local logo, illustration or SVG with no media ancestry is a fingerprinted dependency, with its real rights reference in the source log. Known proof/export bytes remain quarantined even when labeled as a dependency. For an unchanged registered original image, use exact `sourceRef: {"sourceId":"registered-original-id"}`; the local bytes must match that original. For an extracted/generated still, use exact `sourceRef: {"assetId":"registered-generated-id","recordHash":"<64-hex receipt hash>"}`. The canonical coordinator checks the registered parent receipt and its exact output bytes before the browser opens, and admission traverses the real parent ancestry. Do not point an extracted still directly at a raw video source or invent a parent receipt. Unknown sourceRef shapes fail validation.
