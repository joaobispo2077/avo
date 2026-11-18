# /avo.motion reference

**Motion engine gate:** Apply [shared arguments](arguments.md) and inspect native
`animation engine-show` with available context before motion-specific skill/setup.
HyperFrames remains the built-in default. For selected code-drawn, follow the
[advanced workflow](code-drawn.md) and common canonical source/review gates.
HyperFrames-only loaders and recipes below apply only to selected HyperFrames.
Unavailable Remotion or incompatible treatments block; never silently substitute.

HyperFrames component kits are engine-specific. Require compatible source and declared capabilities; do not automatically port a kit or substitute an engine.

## Step/state mapping

**Durable state:** pipeline-run.json when present, canonical animation/source/input-lock revisions and actual motion outputs

**Workflow steps:** Validate motion prerequisites → Run motion → Verify and report the motion result

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing required input, a failed or stale gate, a required human decision, or verified motion completion

**Valid next commands:** /avo.animation-qc or /avo.watch

For selected HyperFrames, load [`hyperframes`](../../../.claude/skills/hyperframes/SKILL.md) entry + [`motion-doctrine`](../../../.claude/skills/motion-doctrine/SKILL.md) when building slots.

**Selected HyperFrames product promo / SaaS launch:** load [`product-promo-knowledge.md`](product-promo-knowledge.md) first — curated technique index, render contract, and starter exemplar under `docs/exemplars/hyperframes-product-promo/`.

**Selected HyperFrames short-form vertical (9:16):** load [`short-form-knowledge.md`](short-form-knowledge.md) — 4-layer scaffold, face-mode choreography, audio-sync protocol under `docs/exemplars/hyperframes-short-form/`.

## Density

Default Level 2–3 for explainers; Level 1 for read-heavy segments.

## Built-in motion map and linked storyboard

At planning, authoring and review boundaries, present `motionPlan` from native
`pipeline status` (or `animation plan-show`) with every item's stable friendly
label, purpose, section, current timing/readiness and linked storyboard card.
Show partial and static plans too; no enable flag, model or render is required.
Use the local JSON/Markdown/HTML links from `animation plan-publish` when the
creator needs the complete view. Inspection never publishes implicitly.
Distinguish concepts, sketches and unverified images from actually inspected
rendered evidence; a generated card is not evidence that motion was executed.

Before an approved cut, use `animation plan-propose --request <absolute JSON>`
for untimed concepts tied to the selected brief and exact available heads. Include
section purpose, dominant focus, density and lifecycle; static/no-sound choices
are valid. Offer clear alternatives without a universal zoom or SFX template.
Record exact selected/rejected IDs using `plan-select`. Revise a concept with its
predecessor hash, keeping unchanged IDs/labels and explaining before/after changes.
These choices do not approve a proof or authorize unrelated edits.

After the exact CMap/cut output is approved, `plan-apply` takes the selected
proposal/decision and explicit BMap/Tracks/Animation authoring. Native owners
validate the complete affected set before publication. If interrupted, retry the
same request/operation ID to recover the exact receipt; do not delete the pending
marker, regenerate IDs or overwrite canonical files. Report actual committed
heads and any unavailable current presentation before asking for creator review.

After publication, the map and linked cards use the verified committed heads for
the applied plan while retaining its original proposal basis. Its own writes do
not make it stale. A later canonical revision, stale dependency or changed
selected direction still does. Regenerating these metadata views grants no
rendered evidence or creator approval.

Inspect craft preferences with `animation options-show`; forward the frozen
active request through revisions/resume. New camera, face-anchor, semantic SFX
and other treatment preferences alone do not establish executable readiness.

## Optional source-picture camera controls

Keep camera movement disabled unless explicitly selected. Use native
`animation camera-propose --project <absolute avo.project.json> --video-id <id>
--request <absolute JSON> --json` to freeze selected recipes and the observed
installed runtime. The request follows `avo.motion-proposal.schema.json`'s
`proposeRequest` with operation `camera-propose`, current expected heads and
explicit camera options. Each item names its source fingerprint, original picture
layer, display-correct baseline crop and relative path recipe. This is an untimed
concept, not a media render or a new cut.

Use `plan-select` to record actual item dispositions. After the exact cut is
approved, `animation camera-apply --project ... --video-id ... --request ... --json`
takes an `applyRequest` with operation `camera-apply`, proposal/decision hashes,
current expected heads and explicit canonical BMap/Tracks/Animation payloads.
Animation retains each exact selected `cameraTreatment` in
`components[].extensions.editingCraft` and uses strategy contract 2.0.0. BMap owns
timing and links `contentRef.componentId`; Tracks binds the original picture layer.
The operation prevalidates all owners, protects unrelated graphics/dialogue and
resumes the same request after an interruption. MCP confirmation binds the exact
request bytes. Neither operation approves a proof or master.

Available recipes are push, pull, punch-settle, cut-to-close, speed-contrast,
overlay-return, section-alternate and section-drift. Alternation/drift require an
explicitly selected section base treatment; they are never universal defaults.
Carry the actual predecessor state and allow static holds. Cut-based recipes need
an actual source cut. Face anchoring requires its own selected, validated
trajectory and is not inferred by an unanchored recipe.

The built-in map/cards expose the path's before/during/after states, source,
options/path hashes and planned/authored state without probing media. These remain
unverified intent until normal microproof, Watch, transcript and creator gates
evaluate current output. An installed runtime or a selected concept is not a
suitability rating.

The native route resamples original picture before independent graphics. Its
qualified profiles require square output pixels, matching baseline/output aspect,
verified right-angle rotation/SAR and supported SDR precision. A vertical edit
needs an explicit matching baseline crop; do not invent a crop or stretch footage.
Retimed, HDR/wide-gamut and unqualified precision profiles fail before output.
FFmpeg/FFprobe remain separately installed prerequisites. Runtime changes require
new proposal/validation evidence. See [native limits](../../../docs/source-picture-camera-rendering.md).

Default framing, non-opted-in proofs and existing Shorts routing remain unchanged.

## Common intents → commands

| User asks for | Command / skill |
| ------------- | --------------- |
| Liquid glass cards | [`talking-head.md`](talking-head.md) → talking-head-recut |
| Captions | [`captions.md`](captions.md) → embedded-captions |
| Logo spin / lower third | [`talking-head.md`](talking-head.md) or slot via this command |
| Logo melt / morph | [`general.md`](general.md) → general-video |
| Short motion graphic | [`motion-graphics.md`](motion-graphics.md) |
| Remotion → HyperFrames port | [`remotion-port.md`](remotion-port.md) |
| Screencast oversized cursor | [`screencast.md`](screencast.md) |
| Engine selection/intake | [`framework.md`](framework.md) — run before first slot |
| Product promo / SaaS demo | [`product-promo-knowledge.md`](product-promo-knowledge.md) → product-launch-video |
| Short-form 9:16 + overlays | [`short-form-knowledge.md`](short-form-knowledge.md) → `/avo.shorts` motion phase |
| Wiggly / boil insert (text, image, video) | [`boil-insert-knowledge.md`](boil-insert-knowledge.md) → `motion-graphics` kinetic-type / `/avo.motion` slot |

Run [`framework.md`](framework.md) when framework choice is not already documented.

## Slot layout

```
edit/animations/slot_<id>/
  spec.md
  composition/
  render.mp4
```

Spawn **parallel** sub-agents for multiple slots (SKILL Hard Rule 10).

## Beat map (required before creator review)

Overlays/SFX must store **`anchor_in_source`** (main camera seconds). After any
cut change, recompute `start_in_output` — see [`cuts.md`](cuts.md).

Write **`edit/animations/beat-map.md`** with B-time table (or run
`python -m avo.edl_timeline write-docs edit/edl.json`). Link from `motion_notes`.

## Examples shipped in command

- Cursor logo → liquid glass card spin
- OpenAI logo from folder → melt into verdict card

Preserve brand assets; never invent trademarked logos when user supplies a path.

## Canonical BMap rule

BMap may be created only from the latest explicitly approved CMap revision and
its exact cut-output SHA-256. All cue times use `cmap-output`; raw and semantic
anchors are optional rebase hints. A new CMap approval immediately stales BMap,
tracks, timed animation, candidates, Watch/transcript/QC evidence, and approvals.
Rebase classifies each cue as preserved, shifted, split, removed, ambiguous, or
unsupported. Only unambiguous shifts auto-apply; ambiguity stops for human
judgment.

## Selected artistic guidance

Before style-dependent authoring, run the shared native pipeline status for this project (checkout: `python -m avo.cli pipeline status --project <project> --json`; installed: `avo cli pipeline status --project <project> --json`). Read `briefing.stageContexts.motion` and its exact selected brief, treatment, constraints, exclusions and current canonical-head identities. Treat this context as offered guidance, never proof that a choice was applied, an approval, or permission to change protected content. Current creator instructions and integrity/accessibility/rights rules take precedence. A bypassed or unselected brief adds no creative gate. Do not discover provider history or select a latest profile independently. See [briefstart](briefstart.md).
