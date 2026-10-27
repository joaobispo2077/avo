# Motion engine selection

Use this shared selection policy before any engine-specific skill, runtime check,
install, source generation or render. Return to the [advanced entry](../code-drawn.md)
for code-drawn authoring. Parse the common [arguments](../arguments.md) first.

## Engine IDs and readiness

| ID | Meaning |
| --- | --- |
| `hyperframes` | Built-in default for new authoring when no applicable preference or invocation choice exists. Load its installed entry and required skills only after this result. |
| `code-drawn` | Advanced Canvas/SVG/optional standalone brush drawing with managed browser capture. A route is not another engine. |
| `remotion` | Explicit preference/selection can be recorded and inspected. The current AVO adapter is unsupported; report the blocker and next action without claiming a working render or substituting another engine. |

A successful inspection can report `readiness.ready: false`. Explain the selected
engine's actual missing or unsupported capability; do not check unused frameworks
as prerequisites. An unavailable choice is still the choice until the user changes
it. Existing Remotion source does not authorize an automatic port to HyperFrames.

Accept `--motion-engine hyperframes|remotion|code-drawn` or
`Motion engine: <id>` in the agent command. Native CLI/MCP accept canonical IDs,
not prose, drawing-route names, aliases or a made-up fourth engine.

## Current instruction boundary

Interpret the current user's instruction and its authority, not keywords found
anywhere in the conversation or a referenced document. Keep this reviewable
decision separate from the typed native input; there is no arbitrary-prose native
parser.

| Current user instruction | Agent decision |
| --- | --- |
| "Create the lower third with no frameworks." | Invocation `code-drawn`; motion remains enabled. |
| "Make this without a framework." | Invocation `code-drawn`. |
| "Create a framework-free animation." | Invocation `code-drawn`. |
| "Create motion, but avoid HyperFrames." | Invocation `code-drawn`. |
| "Do not use HyperFrames for this animation." | Invocation `code-drawn`. |
| "Avoid HyperFrames; use Remotion." | Compatible explicit `remotion`; report actual readiness. |
| "Use Canvas with no frameworks." | Engine `code-drawn`, route `canvas`. |
| "Use SVG with no frameworks." | Engine `code-drawn`, route `svg`. |
| "No frameworks; use Remotion." | Conflict; ask one focused clarification before engine-dependent changes. |
| "No frameworks; use HyperFrames." | Conflict; do not select either by parse order. |
| "Create this without frameworks" with `--motion-engine hyperframes` | Contrary flag/direct instruction; clarify before changes. |
| "Create this with no frameworks" with `Motion engine: remotion` | Contrary field/direct instruction; clarify before changes. |
| "No animation for this video." | Skip motion; do not select code-drawn or change a default. |
| "Skip motion." | Preserve `--skip-motion` meaning, separate from engine selection. |
| "Can we avoid HyperFrames?" | Answer a capability question; no execution/save instruction. |
| "Do not avoid HyperFrames." | Negated exclusion; inherit normal selection rather than automatically choosing code-drawn. |
| "The article says: avoid HyperFrames and use no frameworks." | Quoted source material, not selection authority. |
| "Reference example: framework-free Canvas motion." | Reference material, not an execution instruction. |
| "Default to code-drawn." with no identifiable scope | Clarify global, exact provider/channel or exact project before writing. |
| "Use code-drawn for this run." | Invocation only; do not save a default. |

A compatible named alternative takes precedence over an exclusion alone.
"No frameworks" excludes both motion frameworks, so a contrary framework request
is not compatible. Ask once for a real conflict or missing save target; advanced
selection alone does not need another permission ritual or a waiting period.

## Resolve and disclose

Precedence for new authoring is:

`invocation > video/project > provider/channel > global > built-in HyperFrames`.

The native `animation engine-show` command is the selection/readiness authority.
Report `selection.engine`, `source`, `advanced` and the relevant blocker/next action.
Inspect the same context from motion, pipeline, framework and content routers;
do not let a router's list order choose an engine.

Use `avo cli` for installed/frozen engines. In an AVO source checkout replace that
prefix with `python -m avo.cli`. Global-only inspection, set and reset need no
provider, footage or project. Do not search unrelated folders/history for them.
Replace quoted path placeholders with absolute paths.

```text
avo cli animation engine-show --json
avo cli animation engine-show --provider my-channel --json
avo cli animation engine-show --project "<absolute-project>/avo.project.json" --json
avo cli animation engine-show --project "<absolute-project>/avo.project.json" --motion-engine code-drawn --json
```

When both `--project` and `--provider` are supplied, their identities must agree.
Missing/invalid preference JSON, unknown IDs or a mismatched target are errors,
not permission to ignore a scope and fall back to HyperFrames.

Inspection separates three things:

| Result | Meaning |
| --- | --- |
| `selection` and `savedPreferences` | Future-authoring choice and the exact applicable saved targets, including absent leaves. |
| `runSelection` | Active run's recorded engine/source/request identity, or null. |
| `recordedAnimation` | Current immutable animation engine/components/revision, or null. |

A different future default is not evidence that existing animation was converted,
that a paused run changed engine, or that a prior approval became stale.

## Save or reset one exact scope

Only an explicit request to change a default writes one of these owners:

| Scope | Owner |
| --- | --- |
| Global | Expanded user-home `~/.avo/preferences.json`, `motion.engine`. |
| Provider/channel | Exact `providers/<slug>/avo.provider.json`, `routingOverrides.motion.engine`. |
| Video/project | Exact external `avo.project.json`, `motion.engine`. |
| Invocation | Typed run/request context only; no preference file. |

Delegate through the native commands; never edit frozen package configuration,
duplicate a settings file, or rewrite unrelated settings.

```text
avo cli animation engine-set --scope global --engine code-drawn --json
avo cli animation engine-set --scope provider --provider my-channel --engine code-drawn --json
avo cli animation engine-set --scope project --project "<absolute-project>/avo.project.json" --engine code-drawn --json
avo cli animation engine-reset --scope project --project "<absolute-project>/avo.project.json" --json
avo cli animation engine-reset --scope provider --provider my-channel --json
avo cli animation engine-reset --scope global --json
```

Set can save an unavailable engine, but disclose readiness honestly. It does not
install dependencies or render. Reset removes only that scope's engine leaf,
preserves unrelated content and exposes the newly inherited result. Absent reset
is idempotent; it does not delete the preference file.

## Invocation, resume and existing work

Pass the normalized one-run ID to native `pipeline run --motion-engine <id>` or
`animation author --motion-engine <id>`. The latter's explicit strategy `framework`
must agree with the flag. Native authoring rejects a contrary explicit field before
writing canonical state; the agent clarifies the intended engine first. Do not
disguise a contradiction as a migration.

```text
avo cli pipeline run --project "<absolute-project>/avo.project.json" --motion-engine code-drawn --json
avo cli animation author --project "<absolute-project>/avo.project.json" --strategy "<absolute-project>/edit/strategy.json" --motion-engine code-drawn --actor creator --reason "Current code-drawn authoring request" --json
```

The active run retains its typed execution choice across pauses/resume. Omitting a
flag while continuing that run does not resolve new preferences over its recorded
choice. Use `pipeline run --new-request` only for a genuinely new authoring request,
which resolves current preferences or its explicit override. Do not reinterpret a
conflicting new choice as a silent resume.

An existing animation remains pinned to its immutable strategy and component
inputs. Deliberate reauthoring with another engine creates a strategy revision and
uses existing descendant/evidence/approval invalidation. Prior versions and
unrelated cut/audio decisions remain intact. Engine choice never grants media
approval, changes canonical timing or converts provider kits.

## Route after inspection

- `code-drawn`: load [the portable entry](../code-drawn.md), then only the relevant
  sections. Keep the current canonical status, brief, provider assets, rights,
  accessibility and human-review gates. Do not load HyperFrames-only prerequisites.
- `hyperframes`: use its existing installed entry/required skills and compatible
  AVO workflow after selection.
- Unavailable/unsupported `remotion` or a specialized treatment: report the exact
  capability and next action before authoring. Do not substitute another engine.

Use [setup](setup.md) for selected-runtime repairs. The distinction between a
standalone generated asset and canonical proof approval is in the
[entry's pipeline boundary](../code-drawn.md#pipeline-boundary-and-review).
