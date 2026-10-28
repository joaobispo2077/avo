# /avo.shorts reference

**Motion engine gate:** Apply [shared arguments](arguments.md) and inspect native
`animation engine-show` with available context before motion-specific skill/setup.
HyperFrames remains the built-in default. For selected code-drawn, follow the
[advanced workflow](code-drawn.md) and common canonical source/review gates.
HyperFrames-only loaders and recipes below apply only to selected HyperFrames.
Unavailable Remotion or incompatible treatments block; never silently substitute.

A standalone code-drawn render does not establish automated Shorts support. Require the native motion path to report selected-engine support and current canonical admission; if absent, stop at that capability boundary before invoking HyperFrames.

## Advanced code-drawn bound alpha

For selected `code-drawn`, the native Shorts producer composites an already
registered canonical drawing alpha over original picture and independent audio.
It does not compile a HyperFrames project, run a HyperFrames check/contact sheet,
or generate a HyperFrames caption/widget layer. Follow the
[advanced entry workflow](code-drawn.md) and
[render contract](code-drawn/render-contract.md) for authoring and materialization.

In a normal Shorts request, place `motionEngine: "code-drawn"` and its
`codeDrawn` binding in `defaults` or one candidate. These are typed request
fields, not slash-command flags. Use actual producer references:

| Field | Required identity |
| --- | --- |
| `codeDrawn.instanceId` | Exact current canonical drawing instance. |
| `codeDrawn.manifestRef` | `{path, sha256}` for its current source manifest; path is relative to the footage root. |
| `codeDrawn.inputLockRef` | `{path, sha256}` for the original frozen input lock used to render the alpha. |
| `codeDrawn.generatedAssetRef` | `{assetId, recordHash, locator}` for the actual sealed registered receipt. |

A candidate engine override wins over shared request defaults. Declaring both a
contrary engine and a code-drawn binding in the same scope is invalid, even if a
stronger candidate would mask it. New native resolution consults global,
provider/channel and project preferences and pins each resolved item. Explicit
request choices win. Existing approved plans without a motion field keep their
historical HyperFrames route; saved preference changes do not reinterpret them.

The initial code-drawn Shorts path requires the original-picture source-fidelity
10-bit output profile, one contiguous original-source segment at speed 1, and the
same selected canonical content. Alpha must be silent with straight transparency,
fill the entire canvas, and match the exact dimensions, rational frame rate and
frame count/duration. A resized preview requires a new compatible bound alpha.
Non-fidelity output, split layout, automatic HyperFrames callouts/widgets,
punch-ins and visual inserts fail before preparation. Author supported graphics
inside the drawing instead of requesting an automatic style port. An unavailable
Remotion route or incompatible treatment never authorizes a HyperFrames fallback.

Nonempty planned captions must actually be authored into the inspectable drawing
source. Declare `extensions.shortsCaptionPlanHash` in its manifest: SHA-256 of
the exact resolved `captions` array as UTF-8 canonical JSON, with sorted object
keys, preserved Unicode, no separator whitespace and no non-finite numbers.
Preserve text, word IDs and times. An absent or mismatched declaration blocks
before browser/media work. Empty captions need no declaration. After authoring
or changing captions, refresh source file fingerprints and the manifest seal,
freeze a new original input lock, regenerate/register the alpha, update the
request binding and resolve a new plan revision. The hash declares authored
intent; it is not proof of visible accuracy or human approval.

The native path checks the current canonical heads, source range, full-canvas
placement, source closure and forbidden-output inventory. It observes the actual
runtime and compares fresh RGBA frame hashes with the original receipt before
admission, again after encoding before report publication, and before reusing a
saved proof. Its report binds the receipt, original input lock, generator,
original picture and independent audio. Unused HyperFrames template files do not
determine a code-drawn proof's freshness. Complete the separate human watch,
caption/accessibility, rights and delivery gates in
[QC and delivery](code-drawn/qc-delivery.md).

## Step/state mapping

**Durable state:** shorts.status.json for the batch/item

**Workflow steps:** Validate shorts prerequisites → Run shorts → Verify and report the shorts result

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing required input, a failed or stale gate, a required human decision, or verified shorts completion

**Valid next commands:** /avo.watch or /avo.deliver

**Orchestrator** for one or many YouTube Shorts (vertical ≤60s shelf intent).
Distinct from [`guidelines-shorts.md`](guidelines-shorts.md)
(`/avo.guidelines --shorts` = diagnosis only). Users provide editorial,
review, and delivery parameters; HyperFrames stays internal.

## Phase 0 — Diagnosis

Load [`guidelines-shorts.md`](guidelines-shorts.md) checklist. Record in project notes or `avo.project.json`:

**HyperFrames motion (phase 3):** when not `--skip-motion`, load [`short-form-knowledge.md`](short-form-knowledge.md) before authoring 9:16 overlay slots — scaffold, face-mode, edited-time sync.

| Field | Values |
| ----- | ------ |
| Mode | `native` (vertical source) \| `from-master` (extract + reframe) |
| Viewer promise | hook + payoff |
| Rights posture | music, clips, reused-content |
| Caption intent | identity if known |

## Batch planning contract

For several Shorts from one approved master, collect:

- provider, master path/fingerprint, word transcript or permission to create it;
- requested count, destination, language, output profile, and maximum duration;
- diagnosis, viewer intent, traffic posture, limitations, and rights risks;
- shared speed/layout/caption/review/delivery policies;
- one distinct candidate per requested output with idea, promise, title,
  transcript evidence, range, and editorial approval reference;
- optional per-Short overrides and optional insertion policies.

Persist the result as `edit/shorts/<batch-id>/shorts.request.json`. Then run:

```bash
python -m avo.shorts validate <request>
python -m avo.shorts resolve <request> -o <batch>/plans/shorts.plan-v001.json
```

For request v1.1, use the canonical resolver instead of choosing each output
path independently:

```bash
python -m avo.shorts resolve <external-request> --raw-dir <rawDir>
python -m avo.shorts resolve <external-request> --raw-dir <rawDir> --batch-dir campaign/<batch-id>
```

Every later stage receives the same `--raw-dir`; the recorded `batchRoot` is
validated before work. v1.1 uses ordered `sourceSegments`, writes and hashes
`prepared-lineage.json`, and requires Watch coverage around every join. Never
sort segments by source time or replace them with one enclosing range.

The resolved plan owns exact count, stable order, edited durations, concrete
defaults/overrides, warnings, fingerprints, and required human reviews.
Generated media/HTML never becomes the source of truth.

## Flags

| Flag | Default | Meaning |
| ---- | ------- | ------- |
| `--from-master` | off | Delegate to [`reframe.md`](reframe.md) before captions/deliver |
| `--max-duration N` | 60 | Warn + block promotion over N seconds without EDITLOG override |
| `--skip-motion` | off | Skip motion phase |
| `--identity NAME` | — | Pass to `/avo.captions` |
| `--preview` | on | Stay on 360p/720p until approved |

Batch input also accepts `Count:`, `Master:`, `Transcript:`,
`Destination:`, `Language:`, shared speed/layout/caption policies, and
explicit per-Short overrides.

See [`arguments.md`](arguments.md).

## Workflow phases

| Phase | Action | Reference |
| ----- | ------ | --------- |
| 0 | Shorts diagnosis | [`guidelines-shorts.md`](guidelines-shorts.md) |
| 1 | Transcript-backed candidate request | exact count, promise, evidence, ranges |
| 2 | Resolve immutable batch plan + **human approval gate** | `python -m avo.shorts resolve` |
| 3 | Parameter-driven proof build | full-frame/split, speed, anchor rail, optional insertion |
| 4 | watch-skill LOOP + picture-lock gate | [`watch.md`](watch.md) |
| 5 | Targeted/shared correction and dirty rebuild | preserve approved sibling revisions |
| 6 | Full master QC + immutable delivery | [`deliver.md`](deliver.md) with Short profile |

Executable batch operations:

```bash
python -m avo.shorts build <plan> --stage proof [--short ID] [--workers 2]
python -m avo.shorts qc <plan> --stage proof|master [--short ID]
python -m avo.shorts status <plan>
python -m avo.shorts promote <plan> --approval-manifest <review.json>
```

The approval manifest carries explicit batch gates and Watch references; it is
review evidence, not a way to infer approval. A failed Short moves the batch to
partial state while clean siblings and their hashes remain unchanged.

`--delivery-dir` is a deprecated v1.0 compatibility control. Record
`legacyExternalDelivery` and explain migration to `--raw-dir`/`--batch-dir`.
Reject split delivery for v1.1. Preserve the index, request/approval snapshots,
plans, status, delivery tree, final transcript sidecars, ordered base/insertion
lineage, rights references, disclosures, privacy/safety evidence, and AI-use
evidence. Full contract: [`../../../docs/shorts-batch-paths-and-lineage.md`](../../../docs/shorts-batch-paths-and-lineage.md).

Insertion safety is constructive: AVO resolves identities before render,
materializes exact-duration finite repeats only from approved windows, extracts
only the selected stream into separate audio, records output-to-source maps,
and requires Watch semantic review. Never use HTML media looping or infer
"active gameplay" from freeze detection alone.

## Branch: `--from-master`

1. Confirm approved long-form master exists.
2. User supplies `from`/`to` or phrase anchors.
3. Run [`reframe.md`](reframe.md) workflow → vertical intermediate.
4. Set reframed file as working `Footage` for phases 4–6.

## Duration policy

- Default max: **60 seconds** for Shorts shelf intent
- If export > `--max-duration`: **warn** user; **block** promotion to master without explicit override documented in `EDITLOG.md` or project notes
- Do not silently trim to fit — user must approve structural change

## Manifest hints

```json
"deliverable": {
  "profile": "shorts",
  "maxDurationSec": 60,
  "aspect": "9:16"
}
```

## Escape hatch

Low-level manual chain still valid: `/avo.trim` + `/avo.motion` + `/avo.captions` + `/avo.deliver`. Prefer `/avo.shorts` for consistent gates and duration checks.

Do not create per-project JavaScript/shell patchers or hand-edit generated
HyperFrames compositions. Missing reusable behavior belongs in `/avo.shorts`
contracts, media preparation, templates, validation, or QC.

## Related

- TikTok vertical (different playbook): `/avo.guidelines --tiktok`
- Reframe only: [`reframe.md`](reframe.md)
- Delivery template: [`docs/templates/delivery/delivery-manifest.md`](../../../docs/templates/delivery/delivery-manifest.md)
