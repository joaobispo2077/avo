# /avo.media reference

**Motion engine gate:** Apply [shared arguments](arguments.md) and inspect native
`animation engine-show` with available context before motion-specific skill/setup.
HyperFrames remains the built-in default. For selected code-drawn, follow the
[advanced workflow](code-drawn.md) and common canonical source/review gates.
HyperFrames-only loaders and recipes below apply only to selected HyperFrames.
Unavailable Remotion or incompatible treatments block; never silently substitute.

Asset lookup, rights and freezing remain common. HyperFrames registry/paste-block installation is engine-specific; code-drawn declares local assets and dependencies in its manifest.

## Step/state mapping

**Durable state:** pipeline-run.json plus the current canonical timeline revision

**Workflow steps:** Validate media prerequisites → Run media → Verify and report the media result

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing required input, a failed or stale gate, a required human decision, or verified media completion

**Valid next commands:** /avo.motion

Thin router to **`media-use`** — resolve BGM, SFX, stock images, and brand logos before HyperFrames renders.

## Required args

| Arg | Required | Notes |
| --- | -------- | ----- |
| `Provider` | yes | Brand scope for logo resolution |
| `ProjectDir` or `rawDir` | yes | Workflow root |

## Load skill

- [`.agents/skills/media-use/SKILL.md`](../../../.agents/skills/media-use/SKILL.md)

Run **`--adopt`** first when project already has local assets to register.

## When to invoke

- Before [`motion.md`](motion.md) when using HeyGen catalog or official logo sources
- Content routers (`/avo.launch`, `/avo.music-video`, …) when skill references media-use

## Related

- SOURCE-LOG: log resolved assets in footage projects

## Canonical track integration

### Local sound discovery

Use native `sfx show/search` for existing local sound catalogue metadata before
requesting a new asset. `assets.sfx` is an absolute local read-only source root;
empty project values inherit the provider. `sfx scan --request <absolute JSON>`
explicitly inventories and measures bounded audio, writes a project-local
immutable generation and exposes incomplete coverage/resume. It never renames,
moves, trims or normalizes library sources and never calls footage organization.
`show --offset <n> --limit <1..100>` returns an excerpt plus complete local link.

Record descriptions/categories/tags/material/favorites/variant groups, rights evidence and reviewed markers
with `sfx annotate` against the exact generation. Favorites stay project-scoped;
explicit `sfx favorite-promote` can share selected portable descriptors and the
sound identity with the current provider. Identical audio bytes can share
measurements while separate locators retain different rights/notes. Unknown or
stale rights remain unresolved; search inclusion is not permission to publish.
Present result reasons, native sample audition range, source identity and coverage
before selection. Do not treat a detected attack as a reviewed perceptual marker.

Curated descriptions and categories also contribute descriptor query tokens.
Use an exact `category` filter to narrow a selected sound family. Both optional
annotation fields are limited to 512 characters and can be cleared with `null`.
They remain creator labels; they do not establish measured material, rights or
listening acceptance. Existing entries without those labels need no migration.

Inspect shared preferences with `sfx favorites-show`; removal uses
`sfx favorite-remove`. Mutation requests bind the exact provider document and
confirm their bytes. A selected scan may set `useProviderFavorites: true` to seed
new matching entries, leaving existing project choices intact. Rights, markers,
media and approvals never follow a favorite. See the
[provider-favorites guide](../../../docs/sfx-provider-favorites.md).

Descriptor `sfx search` reads saved metadata only and may correctly return no-match
or silence. Use explicit `sfx search-semantic` only for selected model execution
after actual paired-model/runtime readiness and source/license disclosure. Missing
readiness stays unavailable; do not relabel descriptor matching as semantic.
Neither search operation publishes sound into the edit. See the
[catalogue guide](../../../docs/editing-craft.md#discover-and-curate-local-sounds).

Inspect videoTracks before render: source/generator fingerprint, regions, z-order, fit/crop, compositing, captions/evidence safe zones, and face avoidance. Every contribution links to BMap intent; unresolved or changed sources block.

The motion plan shows named production audio and picture tracks with the exact
declared order, enabled or muted state, levels, channels and program intervals.
Follow a cue link to its storyboard card and check any missing links in the text
or HTML report. Review picture order apart from the stored lane order and check
playback in the encoded proof. Locale delivery audio has its own workflow.

For a declared motion asset need, list existing local options before sourcing
anything new. Use `animation asset-review` to compare numbered candidates against
their intended background and review the supplier, subject and rights evidence.
Record the chosen, rejected or supplied option in `animation plan-select` using
the exact round reference. Keep the placeholder visible until normal canonical
application links the chosen source to the item.

## Selected artistic guidance

Before style-dependent authoring, run the shared native pipeline status for this project (checkout: `python -m avo.cli pipeline status --project <project> --json`; installed: `avo cli pipeline status --project <project> --json`). Read `briefing.stageContexts.bmap` and its exact selected brief, treatment, constraints, exclusions and current canonical-head identities. Treat this context as offered guidance, never proof that a choice was applied, an approval, or permission to change protected content. Current creator instructions and integrity/accessibility/rights rules take precedence. A bypassed or unselected brief adds no creative gate. Do not discover provider history or select a latest profile independently. See [briefstart](briefstart.md).
