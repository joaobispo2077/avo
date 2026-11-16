# Editing craft: preferences and motion review

AVO includes a motion map, linked lightweight storyboard and track/readiness
summary at applicable motion planning and review boundaries. Partial, unresolved
and static plans remain useful. These are views of the current edit and selected
intent, not another timeline or an approval.

Status inspection does not decode media, run models, install tools, render or
initialize canonical records. It reports missing inputs and distinguishes planned
concepts from inspected rendered evidence. An item keeps its existing cue or
proposal identity when display order changes.

## Inspect and publish

Use an absolute project-manifest path with these native commands:

```text
avo cli animation plan-show --project <absolute avo.project.json> --json
avo cli animation plan-publish --project <absolute avo.project.json> --json
```

`plan-show` reads current metadata and reports whether matching published files
exist. Optional `--proposal-hash <sha256>` reopens one saved untimed draft without
selecting it. `plan-publish` explicitly writes immutable review files beneath the
footage project's `edit/review/motion-plan/` directory. Publishing does not alter
the edit or approve it. A changed basis leaves earlier reports historical.
Tampered or incomplete reports are not advertised as current.

Normal native motion authoring publishes the view after its canonical write.
If presentation publication fails, the edit is retained and the response identifies
the missing current review and the action needed before creator review.

The MCP tools `avo_animation_plan_show` and `avo_animation_plan_publish` invoke
the same native handlers. Publication is a derived-file write, not a read-only
inspection or permission to change canonical state.

## Creative treatments remain separate choices

Inspect future-authoring preferences with `avo cli animation options-show --json`,
optionally selecting a project or provider. `options-set` and `options-reset`
accept bounded typed request files with an explicit scope, actor/reason and exact
expected document identity. The inspection result supplies the current identity.
Reset removes only that scope's craft preferences and preserves unrelated fields.

Resolution follows built-in defaults, global preferences, provider, video defaults,
project and current invocation. Explicit false survives the merge. The result
shows each leaf's source, masked choices and inactive child settings. For example,
a face-anchor preference beneath disabled camera remains inactive.

Camera movement, shot alternation/drift, face anchoring, SFX matching/layering,
semantic search, fresh reference analysis, spoken notes, speech recovery and editor
handoff are separately selected capabilities. Their preference fields do not mean
the corresponding execution capability has shipped or is ready on this machine.
This implementation increment delivers preferences, review, untimed concept
selection and local sound discovery. Camera execution and the other remaining
treatments retain their spec tasks and qualification checks.

Existing active requests retain their recorded selection. Changing a saved
preference seeds future authoring and never silently reframes, remixes, changes
engine, revises approved content or transfers approval. Motion-engine selection
continues through its existing independent interface.

## Propose, choose and apply motion concepts

The driving agent prepares typed requests for these native commands:

```text
avo cli animation plan-propose --project <absolute avo.project.json> --request <absolute request.json> --json
avo cli animation plan-select --project <absolute avo.project.json> --request <absolute decision.json> --json
avo cli animation plan-apply --project <absolute avo.project.json> --request <absolute apply.json> --json
```

Proposals describe section intent, purpose, focus, density, lifecycle, assets and
source/spoken anchors. They may remain static or omit sound. They carry the exact
available basis and frozen craft selection, and cannot introduce executable output
timing. Friendly item labels remain stable across changes. A revision names its
predecessor and reports the before/after change without renumbering other concepts.

Selection records the creator's exact selected/rejected IDs. It grants no proof
approval. Timed application requires the approved CMap and exact cut-output hash,
and prevalidates the supplied BMap, Tracks and Animation through their normal
owners. Its recoverable receipt reports actual committed heads. After an
interruption, retry the same unchanged request and operation ID; unrelated writes
remain blocked while recovery is pending. Do not remove the pending marker.

MCP equivalents use the same handlers. Canonical `plan-apply` confirmation binds
the exact request bytes; a changed file must be confirmed again. Propose/select
also publish the current linked review without turning that view into approval.

## Discover and curate local sounds

Declare an absolute local sound directory in `assets.sfx` on the provider or
project. An empty project value inherits its provider. Catalogue reads never
enumerate or decode that directory; an explicit scan measures bounded sources and
writes immutable generations under the footage project's `edit/sfx-catalog/`.
It leaves source filenames, folders and audio bytes unchanged.

```text
avo cli sfx show --project <absolute avo.project.json> --json
avo cli sfx scan --project <absolute avo.project.json> --request <absolute scan.json> --json
avo cli sfx annotate --project <absolute avo.project.json> --request <absolute annotation.json> --json
avo cli sfx search --project <absolute avo.project.json> --request <absolute search.json> --json
```

Scans and annotations require the expected catalogue generation and actor/reason.
Source measurements stay separate from curated tags, favorites, variant groups,
rights evidence and reviewed perceptual markers. A measured peak is an anchor
candidate, not a listening decision. Changed source bytes leave existing manual
decisions visibly stale instead of silently carrying them forward.

RMS and peak are normalized linear PCM amplitudes, not loudness measurements.
Spectral centroid uses Hz; attack/decay use seconds; audition ranges and marker
candidates use native source samples. Curation and favorites stay project-local;
shared provider promotion remains pending its explicit scoped route.

Descriptor search uses saved names, tags and measured filters, explains matches,
and returns bounded audition ranges, source/entry identities, rights and analysis
coverage. It does not decode sources or load a model. `show` returns paginated
excerpts and a complete local catalogue link; search cursors bind the exact query,
filters, mode and generation. No-match is a normal result.

`sfx search-semantic` is an explicit separate model-execution operation with its
own MCP tool. It requires separately provisioned paired local audio/text model
artifacts and a qualified offline runtime. Missing readiness returns unavailable;
descriptor scores are never presented as semantic similarity. Actual provisioned
model and human sound-suitability acceptance remains separate from automated
contract and isolation checks.

## Compatibility and validation

Existing CMap, BMap, Tracks, Animation and Sync ownership remains unchanged.
Before an approved cut, concepts stay provisional. BMap owns executable cue timing;
an unresolved proposal cannot establish timing merely by naming a cue.

Typed camera intent uses an explicitly versioned Animation strategy and an atomic
index capability guard. Legacy edits keep their existing format. The pure camera
planner joins BMap intervals to exact original source occurrences, retains frozen
options and evaluates each frame independently, including windowed and backward
seeks. Camera-aware proof plans use version 2; ordinary proofs remain version 1.
A missing qualified renderer returns an explicit unavailable result. These
contracts and evaluator checks do not establish encoded camera readiness.

Focused automated checks cover read-only defaults, partial/static plans,
selection provenance/freezing, schema compatibility, native/MCP parity and
immutable publication with race/tamper safeguards. The complete feature still
requires its broader software gates, encoded media checks and actual creator,
optional-runtime and exact editor-version acceptance. Generated review files do
not establish a completed master.
