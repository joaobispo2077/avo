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
exist. `plan-publish` explicitly writes immutable review files beneath the
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
This implementation increment delivers preferences and review; those treatments
retain their remaining spec tasks and qualification checks.

Existing active requests retain their recorded selection. Changing a saved
preference seeds future authoring and never silently reframes, remixes, changes
engine, revises approved content or transfers approval. Motion-engine selection
continues through its existing independent interface.

## Compatibility and validation

Existing CMap, BMap, Tracks, Animation and Sync ownership remains unchanged.
Before an approved cut, concepts stay provisional. BMap owns executable cue timing;
an unresolved proposal cannot establish timing merely by naming a cue.

Focused automated checks cover read-only defaults, partial/static plans,
selection provenance/freezing, schema compatibility, native/MCP parity and
immutable publication with race/tamper safeguards. The complete feature still
requires its broader software gates, encoded media checks and actual creator,
optional-runtime and exact editor-version acceptance. Generated review files do
not establish a completed master.
