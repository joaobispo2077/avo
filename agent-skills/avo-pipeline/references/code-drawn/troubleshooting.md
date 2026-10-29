# Troubleshoot code-drawn motion

Use [setup](setup.md) to establish the selected runtime and [render-contract](render-contract.md) for source/lock rules. Diagnose the affected field and retained input before changing anything. Preserve prior source revisions, approved work, original locks and valid outputs.

## Read the actual result

`engine-show --motion-engine code-drawn --json` inspects selection and selected prerequisites without installing or saving a preference. Native drawing commands return structured evidence on success. A motion failure reports `code`, `message`, `field`, `remediation` and `blocking: true` on stderr; read the nonzero exit result as a failure.

The native CLI uses exit 2 for invalid/unavailable inputs, exit 1 for render/output-verification failures and 130 for cancellation. A successful shell invocation, package install, browser launch, or existing output filename alone is not evidence of a successful generated asset. Require the expected completed receipt and decoded-output checks.

If the selected engine is unavailable, repair it or obtain an explicit new selection. Do not install/run HyperFrames as an automatic recovery for a code-drawn request. Remotion remains an honest unsupported AVO execution option; saving its name does not create a working adapter.

## Selected runtime and setup problems

| Symptom | Inspect and repair |
| --- | --- |
| `CODE_DRAWN_RUNTIME_MISSING`, missing Playwright/driver | Frozen installation: reinstall/upgrade the AVO engine containing its matched Playwright 1.64.1 driver and internal Node. Installing external Python packages beside the EXE cannot repair bundled bytes. Source checkout: sync the optional `code-drawn` extra in the environment actually running `python -m avo.cli`. |
| Wrong Playwright version | Use the version pinned by this engine/source revision. A different package/driver version is not a silent compatible fallback; re-establish the supported installation before a new lock. |
| External Node override rejected | Unset `PLAYWRIGHT_NODEJS_PATH` and use the bundled matched driver. No second manually configured Node worker is required. |
| Driver exists, managed Chromium absent | Run `avo cli animation runtime-install --engine code-drawn --json`. Installation needs setup-time network access. A system Chrome or an unrelated framework's browser cache does not satisfy the selected managed runtime automatically. |
| Install succeeded but later inspection cannot find the browser | Compare the invoking user and `PLAYWRIGHT_BROWSERS_PATH` between setup and render. Use one intended cache setting consistently; do not rewrite an old lock to claim the new location/environment. |
| Browser download/system dependency failure | Read the bounded installer diagnostic, repair network/cache access or the operating system dependencies needed by Chromium, then retry the explicit native installer. Inspection/check never install automatically. Keep any existing working cache and engine. |
| FFmpeg or FFprobe absent | Install both through a trusted system/portable distribution, put them on PATH for the same process, and rerun selected inspection. Basic code-drawn needs the browser and encoder independently of motion frameworks. |
| Optional brush unavailable during scaffold | Explicitly install with `runtime-install --engine code-drawn --brush`. Verify the pinned local script/license from [setup](setup.md). Canvas/SVG do not need this dependency. |
| Portable brush project works on one machine only | Confirm its own declared `assets/brush.js`, local license and manifest fingerprints traveled with the source. The global provision cache is not required after scaffold; copying only HTML or a rendered video is incomplete. |

The feature's recorded local browser/render evidence is Windows-specific; no executed Linux/macOS render is claimed by these guides. Diagnose the actual host rather than assuming a green result from another OS applies. Managed browser metadata alone does not prove the host graphics stack works.

## Source, assets and bridge problems

| Symptom | Inspect and repair |
| --- | --- |
| `CODE_DRAWN_INPUT_INVALID` before allocation | Use absolute native command paths; confirm JSON fields/types, a valid route, positive integer targets, reduced rational rate, supported sampling and correct background/alpha pair. Check duplicate, traversal, backslash or escaping-symlink paths. |
| Missing input or `CODE_DRAWN_ASSET_NOT_READY` | Restore the exact declared file or create a new source revision containing the intended replacement. Identify the affected file; do not substitute an empty image or remove its declaration to make check pass. |
| Undeclared/external request blocked | Freeze that legitimate dependency locally, declare its actual bytes and license/rights, then reseal the new draft. Correct relative URLs so they match the declared closure. Render-time APIs/CDNs, query variants and unregistered imports remain blocked. |
| Required font loads as fallback or text changes width | Verify local face bytes, family/style/weight declarations, font-load rejection, required glyphs, and readiness before measurement. A readable fallback is not a successful required-font load. |
| Corrupt/blank image | Await decode and verify natural/declared dimensions. Confirm the bytes match the image format and manifest. Do not resolve `avoReady` after catching a decode failure. |
| Missing or rejected `avoReady`/`seek` | The page must expose a Promise and a callable time-addressable function. Resolve ready only after initialization; await all work needed to paint the requested state. Fixed delays and network-idle waits do not replace the bridge. |
| Stage bounds fail | Match `#avo-stage` backing size, CSS dimensions and origin to the manifest. Remove margins, scroll offsets, extra capture surfaces, debug controls and device-scale assumptions. |
| New manifest dimensions/seed do not change the drawing | Scaffold substitutes constants into source; the host does not inject revised manifest values. Keep source constants and render-contract values aligned. Use a fresh target-specific scaffold or revise/reseal the new source closure. Editing only the manifest does not resize/re-time the old page. |
| Browser audio/media error | Keep drawing capture silent. Remove audio/video playback and route narration/music/SFX through the existing canonical pipeline. A previous proof/master cannot be embedded as a substitute picture/audio base. |

A valid source edit still invalidates its old fingerprint and manifest seal. Follow the full [new-version and sealing procedure](render-contract.md#revise-source-before-freezing-inputs). There is no native `refresh` command and no automatic repair of changed source. Do not invent a command or disable hashing.

## Seek mismatch and graphics failure

`CODE_DRAWN_SEEK_MISMATCH` means sampled decoded RGBA pixels disagree across repeated, reversed or fresh-session seeks. It is not fixed by comparing video-container hashes, rendering in only chronological order, or declaring a generous pixel tolerance.

Inspect the first differing frame and simplify its drawing while retaining the failing seek order. Common causes are:

- A persistent PRNG/noise/particle accumulator whose state depends on previous frames.
- Missing reset of Canvas transforms, clipping, alpha, filters or compositing.
- A CSS/SMIL/preview clock, wall-clock read, asynchronous unawaited work or user-input state.
- Layout/text measurement before the required font/image is ready.
- Persistent brush/GPU caches initialized outside the recorded seed contract.

Reconstruct the requested state from the recorded time/seed. For the supported brush route preserve the fresh isolated standalone library instance, seeded vendor initialization, temporary WebGL2 surface, explicit flush, copy and context release for each seek. Clearing one persistent brush canvas or calling its seed API alone did not reset all internal state.

If WebGL2/context-release/graphics checks fail, report brush as unavailable in that actual environment. Repair the graphics setup and rerun check. Do not silently change browser, graphics mode, build or drawing route. A requested Canvas/SVG redesign is a deliberate new source revision and selection within the code-drawn engine.

Changing GPU, driver, browser, encoder or dependency identities can stale a lock even when source bytes are unchanged. Capture a new lock in the intended working environment after proving it; keep the original evidence attached to its original environment.

## Alpha, color and target failures

For black/white background where alpha was expected, inspect every full-frame fill, CSS background, SVG background rectangle, internal WebGL alpha setting and final presentation copy. Use `background.mode: "transparent"` with `alphaMode: "straight"` and leave unpainted regions transparent. Check semi-transparent edges over contrasting backgrounds; an all-transparent blank frame is not a useful overlay.

For an opaque asset, paint the intended explicit background and verify alpha is 255 throughout. Do not use a transparent contract to disguise an accidental missing background.

`CODE_DRAWN_OUTPUT_INVALID` blocks success when decoded dimensions/rate/count/pixels/silence/alpha disagree. Verify the actual FFV1/BGRA Matroska path and the supported sRGB/full-range to SDR BT.709 assumptions. Avoid adding an extra unpremultiply/color conversion or switching to a codec that drops alpha. The current renderer supports only `spatialSamples: 1` and `temporalSamples: 1`; it does not silently implement temporal blur or supersampling.

When a real canonical composite differs despite valid generated-media checks, inspect that composite's placement, scaling, color conversion, layer order and relevant frames after normal admission. Generation-level contrasting-background checks do not replace canonical composite QC or [delivery review](qc-delivery.md).

## Stale locks, revisions and canonical admission

`CODE_DRAWN_LOCK_STALE` can identify a changed file, manifest, source revision, seed, target, generator, input set or observed environment. Compare the current input to the **original** lock. Either restore the original exact input/environment for that binding or create a new immutable source revision and check/freeze/render with new paths.

Never update the original lock at the end of a render, replace its manifest reference with a fresh head, or copy a new digest into an old receipt. `manifestHash` and `inputLockHash` are canonical document seals; a file reference's `sha256` hashes complete saved file bytes. Hashing pretty JSON as if it were the canonical seal produces a mismatch.

A standalone lock/receipt cannot claim canonical approvals or current timeline placement. `code-drawn-check --output-lock` creates standalone provenance. Only the existing canonical coordinator can bind verified current maps/tracks, range and placement and pass the generated asset through admission. Missing/stale canonical evidence is a blocked integration; do not fabricate it or reuse earlier proof picture/audio.

Current defaults apply to new authoring. A changed global/provider/project preference does not rewrite an active run's choice or an existing pinned animation. See [selection](selection.md) before interpreting a retained engine as a failed preference write.

## Encoder failure, cancellation and existing outputs

`CODE_DRAWN_RENDER_FAILED` requires the actual encoder error and exit result to be resolved. A PNG capture sequence or an incomplete `.mkv` is not a finished asset. Check available storage, permissions, the FFmpeg executable used, and decode/verification evidence. Test a small target first; final-resolution work must still pass at its real dimensions and frame rate.

Ctrl+C cancellation reports failure and does not authorize success/admission. The normal attempt closes the browser/encoder and removes its temporary candidate. If a process was killed externally, inspect leftover attempt files; treat them as incomplete, preserve existing valid work, and use a fresh output path after diagnosis.

Scaffold destinations, locks, snapshots, output assets and receipts use no-overwrite behavior. An "already exists" error is a preservation guard: choose a new version/path or inspect the existing artifact. Do not delete source, overwrite approved output, or reseal a receipt as a recovery shortcut. Output/receipt publication must complete together; an unexplained file without a valid matching receipt cannot be promoted.

After repair, repeat the failing check and its relevant frame/encode validation, record the finding and result in the project's review/edit logs, then continue through the existing approval gates. Agent self-scores, elapsed time and silence are not approval.
