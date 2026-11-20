# Optional ArtCraft provider authoring

Begin with the requested component's purpose, required editable behavior, media
output, provider and project context. For a capability question, inspect the
focused bundled catalog with `avo cli artcraft catalog --app <app> --json`.
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
Automated authoring uses a confined runner and verifies the saved document's
fresh-session frames and transparent export against a third native backing.
Use `avo cli artcraft inspect --job <absolute-job-record> --expected-head
<event-hash> --json` to compare the retained job document, inputs and output
records against the current files. A video job also checks the project and
canonical revisions. Inspection is read-only and can run in a fresh session.

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

Before any native authoring, identify the effective roots, owner of the job's
document, output contract and bounds. A provider-only component has a declared
external source workspace. A real video keeps canonical decisions under
`<rawDir>/edit/timeline/` and uses its existing component and media owners.
Keep editable source, fonts, media, plugins, recipe, tool identity and rights
with the exact version. Inspect actual exported frames, samples or exchange
behavior, and obtain the current design and contextual video decisions through
the existing review workflow. Earlier program exports serve as review references.
