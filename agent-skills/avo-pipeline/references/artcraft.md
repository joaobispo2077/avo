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
and `--application` when needed. The selected app and CLI must match releases,
and readiness requires verified file confinement for the requested roots.
Missing or unqualified prerequisites produce a specific readiness result.

Before any native authoring, identify the effective roots, owner of the job's
document, output contract and bounds. A provider-only component has a declared
external source workspace. A real video keeps canonical decisions under
`<rawDir>/edit/timeline/` and uses its existing component and media owners.
Keep editable source, fonts, media, plugins, recipe, tool identity and rights
with the exact version. Inspect actual exported frames, samples or exchange
behavior, and obtain the current design and contextual video decisions through
the existing review workflow. Earlier program exports serve as review references.
