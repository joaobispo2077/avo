# ArtCraft integration strategy

This document covers the integration boundaries and the first Windows AniCraft
lower-third profile. The capability register tracks work on the other profiles.

ArtCraft is specialist authoring for a component that needs it. It is not a new
default motion engine or a normal prerequisite for AVO.

## Separate user-managed installation

AVO does **not** bundle or redistribute ArtCraft applications, their runtimes,
CLI binaries, installers or third-party plugins. AVO setup, update and authoring
flows do not download, install or update them. Users install only the app and
compatible CLI required for the selected operation, separately from the official
distribution; the entire suite is never a normal prerequisite.

AVO ships its own adapters, capability metadata and guides. It can locate an
existing selected installation, verify readiness and explain missing prerequisites.
A missing app/CLI returns an actionable blocked state with official setup
instructions, without modifying PATH, global MCP settings or software installations.

## When AVO may use ArtCraft

| Situation | Result |
| --- | --- |
| Existing approved component or supported AVO route meets the request | Use that route; no ArtCraft discovery or suggestion |
| User directly asks for ArtCraft | Honor the selected app/mode within normal readiness and permission limits |
| A required behavior cannot be supplied by existing reuse/native contracts | Record the exact gap and choose the smallest necessary ArtCraft operation |
| A selected pinned ArtCraft component needs rebuilding | Follow only its recorded source recipe, without changing unrelated defaults |
| Native setup, invalid input, permission, bug or transient failure | Repair/report the existing route; no automatic external-tool fallback |
| Quoted mention or capability question | Knowledge only; no execution authorization |
| Explicit exclusion or incompatible current commitment | Respect it or resolve the direct conflict; no silent substitution |

The selection check runs before app probing, guide loading or connection and is
rechecked before mutation. A caller writing `unsupported` does not prove a gap:
the unmet requirement and considered existing contracts must be reviewable.
Unknown support is unresolved, not assumed unsupported. Existing task authorization
continues to apply; the tool choice itself does not add a new approval ritual.

## Keep ordinary work cheap

Ordinary AVO work must perform zero ArtCraft-specific executable lookups, process
launches, MCP/live connections, documentation fetches and app-guide loads. A small
gateway condition and packaged capability index are sufficient before selection.
Only the chosen app's detailed guidance/commands are loaded after selection.
Do not add ten top-level skills, default suite installation, global MCP setup,
startup scans, background services or periodic documentation refresh.

Prefer one bounded CLI batch for a qualified repeatable recipe. Host MCP can
assist interactive authoring without becoming an AVO runtime dependency. AVO's
own MCP exposes the same narrow coordination flow as its CLI; it does not proxy
every external menu command or embed a multi-server client. Live app access is
explicit and must preserve effective permission and save-ownership boundaries.

Reuse unchanged qualified component output when its full source/dependency/tool/
render identity and current canonical bindings permit it. Still perform fresh
contributing-byte checks. Changed text/source/parameters may require native
rendering; a previous full video proof is never a reusable source or cache entry.

## Extend existing AVO services

Use provider promotion/versioning, component instances, generated-media receipts,
proof composition and current review/cleanup ownership. Keep CMap, BMap, Tracks,
Animation and Sync authoritative in AVO. Do not add ArtCraft apps to the normal
motion engine list or register their effects as native proof implementations.

Current provider publishing assumes UTF-8/HyperFrames source. Add an explicit
byte-safe external-native package path, dependency/rights inventory and
provider-authored provenance rather than fabricating a video or skipping checks.
Keep historical kit paths/schemas valid. Native/media source remains outside the
AVO repo; immutable provider metadata records its exact source closure.

Generated schema roles alone do not implement canonical audio/still use. Extend
actual receipt verification, source descriptors, locks, compiler/preflight and
execution for those roles. An exported audio/image file is generated material,
not an original source. Registration must independently validate reproducibility;
neither a supplied verified flag nor a generator name is evidence.

### Register a verified lower third

Select the video component before authoring. Its Animation component, BMap cue
and Tracks overlay identify the same component. Set the Tracks generator to
`{"adapterId": "artcraft.anicraft", "componentId": "speaker-label"}` using
the selected component ID. Use a full-canvas placement, an explicitly linked
cue and a frame-aligned interval equal to the exported frame count. The current
cut and sync must have their existing approvals.

Choose a 16:9 or 9:16 output contract when preparing the AniCraft job. Each
format is authored at its own canvas size. The portrait plate sits near three
quarters of the picture height, with the entrance, readable hold and exit
inspected on that canvas.

Run `avo cli artcraft register --project PROJECT --job JOB --expected-head HEAD
--asset-id ASSET --output OUTPUT --json` after the selected job reaches
`exported`. Use absolute paths and an existing output folder under the video's
`edit/derived`. Registration saves the exact native source lock next to the
lossless `.mkv` and records both in generated media. The proof uses the standard
`overlay-video` operation with the retained asset and input-lock references.
Window proofs keep the local frame phase of the full composition.

Use `avo cli artcraft review --job JOB --expected-head HEAD --json` to inspect
the standalone before, entrance, hold, exit and after frames. Add `--project
PROJECT --asset-id ASSET --materialization RECORD` to pair the same export with
the current proof, placement and available source and edit logs. A changed
candidate or timeline requires current review evidence. Use the existing
creator approval workflow to record the decision.

### Publish a reusable native source

For the qualified AniCraft lower-third profile, `avo cli artcraft
provider-propose` reads a sealed package and a general provider pattern. The
package identifies the editable native source, recipe, parameter schema,
source review, design approval and rights. Every file has its exact size and
SHA-256. Use the selected provider, absolute catalog and package paths, and
the explicit external `--source-root` for the proposal.

`avo cli artcraft provider-publish` applies the creator decision to that
proposal and its same source package. Pass `--expected-catalog` with the
current catalog hash and `--native-store` with the existing external library
folder. AVO preserves the verified bytes under the selected provider and
package hash. The catalog records the native app, exact package identity and
the source, design and rights fingerprints.

`avo cli artcraft provider-instantiate` pins an exact catalog version for a
particular video. Supply its project, approved catalog and native store, kit ID,
version, manifest hash and a fresh instance ID. The `--bindings-json` object
contains `parameters`, `assetBindings`, `eventBindings` and `safeAreaBindings`.
The selected parameters must match the published template contract. AVO copies
the source into the selected footage project for subsequent qualified authoring.
Omitted fields inherit the reviewed template parameters, including its font.
Choose a separately reviewed source design to change that font.

Select a newer version with a fresh instance ID and `--supersedes` to link the
upgrade explicitly. Review the new instance in the video's own context.

To render a pinned video's label, select its copied `.anicraft` file as
`document.source` with `document.state` set to `saved` in `artcraft prepare`.
Include its owning source directory in `readRoots`, the instance's selected
`authoringParameters`, and its matching native output contract. A qualified
confined CLI run saves a separate native revision and records the original as
a dependency. The verified profile edits the label using the approved font,
then verifies the saved design and alpha frames. Register the resulting
export and review it against the current video proof.

For an exact repeat of an already verified saved-source label, use
`artcraft prepare` with `--mode reuse`, `--reuse-job` and `--reuse-head`.
Select the same provider, editable source bytes, label parameters and output
contract in the new video. `artcraft run` copies the retained native revision,
recipe and ordered alpha frames to the new job without launching AniCraft.
Register the copy for its new timeline independently. Changed inputs select
the corresponding new authored job.

The checked automatic profile requires a host with independently enforced job
roots. Returned files from the current guided handoff stay available for
inspection and reference while production qualification continues.

## Qualification and rollout

Begin with one real lower-third delta in one qualified motion app. Add editable
sound only when necessary/requested, then qualify specialist tasks without
turning them into default dependencies. All ten applications remain in the full
[capability coverage](artcraft-capabilities.md); partial delivery stays partial.

Use forbidden-call tests to prove at least 20 ordinary/failure requests cause
zero ArtCraft activity. Native trials separately qualify author/save/reopen/
export, exact clocks/alpha/color/samples, recovery, three-project reuse and
five-editor usability. Normal CI does not need the suite. Unknown native behavior
remains blocked/unverified until tested on the exact release/platform.

App modes are not equivalent isolation boundaries. A failed batch can retain
earlier mutations; a dropped connection or stdin EOF does not prove render stop.
Inspect unknown write outcomes before retrying and never silently broaden roots,
switch to live control or install more apps. Existing creator and cleanup gates
remain unchanged.

Implementation must document its actual boundaries in ARCHITECTURE.md and retain
the canonical AGENTS.md selection rule. This strategy selects no new framework,
model, background service or compulsory dependency.
