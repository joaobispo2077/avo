# Optional ArtCraft provider authoring

Begin with the requested component's purpose, required editable behavior, media
output, provider and project context. For a capability question, inspect the
focused bundled catalog with `avo cli artcraft catalog --app <app> --json`.

Open the guide for the selected operation when it is needed.

- PhotoCraft, LightCraft, FigCraft and DeckCraft standalone reviews. [Still review profiles](artcraft/still-review.md)
- EffectCraft masked lower third with a bounded transparent span. [EffectCraft review profile](artcraft/effectcraft-mask.md)
- TextureCraft material and packed-texture exchange when qualification is requested. [TextureCraft prerequisites and file handling](artcraft/texturecraft.md)
Catalog entries report documented behavior and the scope of its evidence.

## Assess one request

Use `avo cli artcraft assess --request-json <structured-request> --json` or the
equivalent AVO MCP tool. Add `--app <app> --operation <operation>` for an explicit
current ArtCraft choice. Apply the existing engine selection for the rest of the
video. A current exact component may supply reusable media or a pinned recipe.
For a required capability gap, identify the exact unmet behavior, compare the
current applicable AVO and reuse contracts, and retain their inspected evidence.
An unavailable tool, input error, permission failure, timeout or renderer defect
goes through the existing repair path.

Assessment establishes selection. The separate authoring qualification requires
the selected app and matching CLI separately installed from their official source,
an authorized external workspace, actual permissions for the selected mode, and
complete editable source and dependency evidence. A user-installed app is only
needed when its specific qualified operation is selected. AVO ships its own
integration metadata and code.

## Preserve source and review

For the selected AniCraft lower-third profile, `avo cli artcraft prepare`
accepts `--request-json`, `--job-spec-json`, `--provider`, `--workspace`,
`--app anicraft`, `--operation lower-third` and `--mode cli`. The job options
declare an empty or saved native document, permitted source roots, an output
contract and resource limits. Choose explicit installed paths through `--cli`
and `--application` when needed. The selected app and CLI must match releases.
Automated readiness requires verified file confinement for the requested roots.
Missing or unqualified prerequisites produce a specific readiness result.
Windows AniCraft 0.2.1 supports an explicit `--mode guided` job. Set
`authoringParameters.primaryText` and `authoringParameters.font` in the job
options and start from an empty document. `artcraft run` returns the staged
recipe and runnable native steps for an operator. The returned native document
and opaque PNG sequence stay reference-only until separately qualified. For the
initial lower third, inspection validates the editable label, font family,
timings, selected graphic and inline paths directly from the native document.
The selected app's installed command signatures are captured at preparation.

Set `authoringParameters.secondaryText` to add an optional editable second
line to a new AniCraft lower third. Use one line of up to 48 characters.
Both lines use the selected installed font, and the adapter checks that the
secondary line fits the plate. A saved-source revision can change the text in
the approved design's existing slots.

For a reduced-motion AniCraft lower third, set `authoringParameters.motion`
to `"hold"`. AVO verifies a fixed plate with clear starts and ends. Omit
`motion` for the current slide. Text revisions preserve the selected motion.
To change it, approve and select a separate native design.

The current lower-third profile supports declared 16:9 and 9:16 canvases.
Review the text size, face and caption clearance within the selected format.
Automated authoring uses a confined runner and verifies the saved document's
fresh-session frames and transparent export against a third native backing.
Use `avo cli artcraft inspect --job <absolute-job-record> --expected-head
<event-hash> --json` to compare the retained job document, inputs and output
records against the current files. A video job also checks the project and
canonical revisions. Inspection is read-only and can run in a fresh session.
If evidence changed, inspection reports the affected files and the relevant
rebuild or review actions. The AniCraft lower-third profile can also report
edited text or font values from the selected native document.

Use `avo cli artcraft recover --job <absolute-job-record> --expected-head
<event-hash> --json` after an interrupted run. Recovery reports the next action
and compares retained files with the recorded partial fingerprints. Use
`--action retry` for an unchanged prepared job or to recover its exact completed
result after a lost response. Use `--action cancel` before authoring starts.
Active CLI cancellation requires its confined runner to own the exact running
job and confirm that its processes and writes have stopped. The cancellation
receipt keeps partial files as inspection references. For an operator-owned
handoff, have the operator resolve the writer's state before recovery.
The AVO MCP tools
`avo_artcraft_prepare`, `avo_artcraft_run`, `avo_artcraft_inspect` and
`avo_artcraft_recover` use the same job controls and exact event heads.
Pass the request and job specification as structured objects in MCP.

Choose `--mode host-mcp` to stage the selected AniCraft Windows 0.2.1
headless stdio handoff for an independently confined host. Use the returned
initializer, launch arguments and fingerprinted recipe under the listed
operator roots and budgets. The native MCP script uses `command` and `params`
for each step. Check its step results and saved document, then run AVO
`artcraft inspect` at the handoff head. Operator-returned source and PNG files
are reference material until separately qualified.

For the selected Windows 0.2.1 runtime, `--mode json-lines` uses `serve` through
a runner that independently confines the chosen roots and supports bounded
stdin/stdout. AVO sends one fixed native command at a time and stops on an
invalid or failed reply. Both batch and JSON-lines check each result and the
acknowledged save destination before accepting a new document. AVO verifies
reopened frames and alpha against the same contract in either mode.
A reply arriving after its deadline is rejected before AVO inspects scratch.
The selected profile audits the owned frame folders under the same limits.
A verified lower-third export from this profile can
enter the ordinary proof admission and saved-source reuse paths. When the
confined runner is unavailable, use the explicit guided route for an
operator-owned handoff.

Selected specialist jobs run fixed recipes and validate the app-specific
results before accepting saved work. PhotoCraft's editable Curves profile uses
`run` with its selected commands. Recorded action sets, batch folders and
droplets remain outside that qualified profile.

For an editable isolated SoundCraft cue, use `--app soundcraft --operation
isolated-cue --mode cli` with the selected Windows 0.20.1 tools and a confined
runner. Select a source WAV using `soundCue.source` and choose the built-in
`room-reverb` with `soundCue.effect`. Use the `editable-isolated-cue`
requirement and a `generated-audio` WAV output with 48 kHz stereo and an
explicit sample count up to ten seconds. Review locates the independently
decoded cue, native session and retained dry audio dependency at the exact
exported job head. The existing mix and review workflow own contextual use.

To include that cue in a sound-enabled proof, place the review's `audio`
fingerprint and `generatedAudioRef` on an SFX layer in Tracks. Use its
`sourceId` and the same `generatedAudioRef` in the proof's corresponding
trim operation. Set its source descriptor to the exported WAV, stream zero,
and `mediaClass: generated-asset`. Use the selected program-frame region and
48 kHz stereo node. The proof compiler checks the placement and rejects
overlapping uses of the same cue. The existing gain, fade and mix operations
control audition level and preserve the original dialogue processing.

For an editable static card, explicitly select `--app vectorcraft --operation
vector-still --mode cli` with the selected Windows 0.24.1 tools and a confined
runner. Use the `editable-vector-card` behavior, `authoringParameters` with its
label and font, and a `generated-still` contract for straight-alpha sRGB PNG.
The job retains editable text, vector paths and the independently measured PNG.
Use the review's `still` fingerprint and `generatedStillRef` on a Tracks overlay
layer. The proof's `overlay-image` operation uses the same receipt, layer,
native dimensions, placement and frame range. It holds the image on those
frames and preserves the original audio.

For an animated emblem, explicitly select `vectorcraft` with operation and
request behavior `vector-emblem` in confined CLI mode. The Windows 0.24.1
profile authors one editable 128 × 128 star and verifies its straight-alpha
sRGB SVG export. Use the review's `artworkRef` as the `artworkRef` in a second
job for the same provider and component. Explicitly select `anicraft` with
operation and request behavior `animate-vector-emblem` in confined CLI mode.
Its Windows 0.2.1 profile produces a 320 × 180 straight-alpha sRGB PNG sequence
of 24 frames at 24 fps. Include the upstream records and output in the selected
read roots. The prepared motion job retains both editable sources. Add a
separately selected SoundCraft cue with the existing SFX Tracks workflow when
the video needs sound.

For a source-linked FilmCraft return, explicitly select `--app filmcraft
--operation source-linked-timeline-return --mode cli` using the selected
Windows 0.20.1 tools and a confined runner. Use a blank document, an
`interchangeSource` containing one original MP4 or MOV with its canvas size,
and a `timeline-interchange` OTIO output with the frame rate and frame count.
The selected profile retains a native project, recipe and one picture and
stereo audio clip linked to that original. Run `artcraft import-timeline` with
the exact job head, target project, actor and reason to prepare and validate the
import for review. Reported losses, unsupported treatments or a former proof
leave the return reference-only. Activation follows the existing sync and
creator gates.
FilmCraft also compares the original's picture stream with retained local MP4,
MOV and Matroska outputs. A match leaves the return reference-only and names
the retained output, including when its container differs from the input.

For a video job with a verified export, select an Animation component, its BMap
cue and the linked Tracks overlay before authoring. Register the exact exported
job with `avo cli artcraft register`, the current project and an owned `.mkv`
path under `<rawDir>/edit/derived`. Use the resulting generated asset and its
source lock in the standard `overlay-video` operation. Keep the canonical
canvas, timing, straight alpha and layer order. Check a short proof window across
the entrance, hold and exit, then verify the context in the original-footage
proof. Review text at mobile size and check it against faces, captions and other
graphics. Record the design decision against the exact candidate and context.

Run `avo cli artcraft review --job <absolute-job-record> --expected-head
<export-event-hash> --json` to locate the exact standalone phase frames. Add
`--project`, `--asset-id` and `--materialization` to include the matching
original-footage proof and the current project logs. Use the existing human
review workflow to record the decision.

For an explicitly reviewed provider lower third, prepare a native package with
the original editable source, recipe, typed local parameter schema, source
review, exact design decision and rights. Use `avo cli artcraft provider-propose`
with that package, the selected provider and the external source root. An
explicit `provider-publish` applies the decision against the current catalog
hash and retains the package under the selected external library root. Keep
the approving actor and reason tied to the exact source version.

Use `avo cli artcraft provider-instantiate` for a selected video. Pass the exact
kit version and manifest hash, the external native store, a fresh instance ID
and the typed parameter and binding object. AVO preserves project-owned copies
of the native source and its evidence. For a deliberate upgrade, select the
newer version and pass `--supersedes` with the earlier instance ID.
Use the reviewed template's font. Omitted fields inherit its approved values.

For an explicitly shared kit, the origin provider publishes a version whose
native-source rights entry names the recipient and references the rights evidence.
Add a `sharing` object with `providers`, a list of exact provider slugs, and
`evidenceRef`, the reference covering that permission. Select the published kit
from the recipient's project using `--source-provider` with the origin slug.
The project instance retains the origin, recipient and fingerprinted rights.

To add an optional identity mark to a lower-third job, select its verified
VectorCraft emblem with `artworkRef` in the AniCraft CLI job specification.
Use the same provider and component and authorize the upstream export and
native evidence in the job's read roots. The mark stays editable beside the
label. Carry the same `artworkRef` through saved-source text edits and exact
copy-only reuse.

A provider kit can retain the corresponding SVG as `identity-artwork` in
its file manifest. Add the SVG fingerprint as `identityArtworkSha256` in the
design review and include a rights entry for each of the native document and
SVG. When granting reuse to another provider, both rights entries must name
that recipient. The kit and each selected video instance keep byte-exact copies.

To reserve space in a video, supply `safeAreaBindings` for `faces`, `captions`,
`evidence` and `ui` when pinning an AniCraft kit. Each region is a rectangle
with integer `x`, `y`, `width` and `height` in the reviewed kit canvas. AVO
rejects regions outside the canvas or inside the lower third's allowed
visible bounds, including its entrance and exit. Use empty arrays when the
video has no regions to reserve.

For a saved-source text revision, set `document.state` to `saved` and
`document.source` to the selected project-owned `.anicraft` copy. Include
the source directory in `readRoots` and choose the instance's text and approved
font. For a kit with retained identity artwork, use `artworkRef` with the
`instanceId` and `instanceHash` returned by `provider-instantiate`. Include
the video-local kit directory and the instance record directory in `readRoots`.
Use the instance's selected parameters and the package's exact output contract.
Run the selected qualified confined CLI profile. AVO keeps the original and
saves a separate revision with its recipe and edit-command evidence.

For optional sound, first place the verified SoundCraft export on an unmuted
SFX layer in Tracks. Link its region to the kit's picture cue in BMap. When
pinning the kit, add an `eventBindings` entry with `slot: "sound-cue"`, the
Tracks `regionId` as `eventId`, and the active Tracks hash as `revisionHash`.
Register an identity kit selected through `artworkRef` as usual. For a plain
kit, pass `--kit-instance-json` with its `instanceId` and `instanceHash` to
`artcraft register`. When preparing the saved-source job, include the exact
video-local kit folder and instance record directory in `readRoots`.
AVO verifies the pinned source, checks the current sound selection and requires
the sound to start during the kit's picture cue. The Tracks placement owns
the sound mix.

For a byte-identical repeat, use `--mode reuse` with `--reuse-job` and
`--reuse-head` from the verified saved-source run. Keep the same provider,
editable source, parameters and output contract. The new run copies the
verified component frames and native revision. Use the new video's canonical
placement and review before adopting the result.
Keep the selected run's job and event journal, editable export, recipe and
frames. Inspection and reconstruction verify those files against their recorded
fingerprints. If any of them changes, verify a new export before reusing it.
Reconstruction checks linked VectorCraft artwork against retained outputs and
reports matching proof or preview ancestry. A pinned lower-third package must
contain only its supported source roles. An added plug-in blocks the rebuild.

Before any native authoring, identify the effective roots, owner of the job's
document, output contract and bounds. A provider-only component has a declared
external source workspace. A real video keeps canonical decisions under
`<rawDir>/edit/timeline/` and uses its existing component and media owners.
The file and byte limits apply to the combined selected inputs and separately
to the retained export. An export that exceeds those limits or misses the job
deadline goes to reconciliation.
PhotoCraft, LightCraft, FigCraft, DeckCraft, and EffectCraft also check each
command reply and stop scanning scratch as soon as a job limit is exceeded.
Readiness requires one valid signature for each selected command. A saved-source
job needs a free revision path before it can open the selected app.
Keep editable source, fonts, media, plugins, recipe, tool identity and rights
with the exact version. Inspect actual exported frames, samples or exchange
behavior, and obtain the current design and contextual video decisions through
the existing review workflow. Earlier program exports serve as review references.
