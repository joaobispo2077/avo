# /avo.talking-head reference

**Motion engine gate:** Apply [shared arguments](arguments.md) and inspect native
`animation engine-show` with available context before motion-specific skill/setup.
HyperFrames remains the built-in default. For selected code-drawn, follow the
[advanced workflow](code-drawn.md) and common canonical source/review gates.
HyperFrames-only loaders and recipes below apply only to selected HyperFrames.
Unavailable Remotion or incompatible treatments block; never silently substitute.

Keep approved cuts/audio and canonical cue/placement ownership. Existing HyperFrames cards/kits need an explicit compatible implementation; no automatic port is implied.

## Step/state mapping

**Durable state:** the child pipeline-run.json and its parent timeline lineage

**Workflow steps:** Validate talking head prerequisites → Run talking head → Verify and report the talking head result

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing required input, a failed or stale gate, a required human decision, or verified talking head completion

**Valid next commands:** /avo.watch

**Orchestrator** for talking-head / interview **graphic overlay packaging**. Distinct from [`captions.md`](captions.md) (verbatim subtitles) and [`shorts.md`](shorts.md) (Shorts shelf).

## Preconditions

- [ ] `provider` + `rawDir` + `Footage:` declared
- [ ] Existing clip plays in full — **no re-timing or recut** unless user explicitly requests trim first

## Phase 0 — Route check

| User wants | Route |
| ---------- | ----- |
| Graphic cards, lower-thirds, data callouts | This command → `talking-head-recut` |
| Spoken-word subtitles only | [`captions.md`](captions.md) |
| Explicit source-picture push/pull/punch/reframe | Native [camera controls](motion.md#optional-source-picture-camera-controls), before independent overlays |
| Single motion sting | [`motion.md`](motion.md) |

## Workflow phases

Create an isolated child timeline with its exact parent reference before writes.
Forward explicit craft options and source identity to the child's normal motion
owner; this Profile cannot change the parent or grant itself canonical ownership.
Always show the child's built-in motion map and linked storyboard, including
static/provisional cards. Use [motion concept planning](motion.md#built-in-motion-map-and-linked-storyboard)
to propose/select treatments before approved-cut timed authoring. Camera movement,
alternation, face anchoring and SFX remain separate explicit choices whose actual
execution readiness must be checked. An option declaration is not an applied zoom.

For selected camera movement, use `camera-propose`, actual `plan-select`
dispositions and recoverable `camera-apply` inside the child. Preserve the source
fingerprint, display-correct baseline crop, exact path/options and current heads.
Review the built-in before/during/after camera states before rendering. Keep
graphics/captions independent, preserve dialogue and show static alternatives.
Section alternation/drift and face anchoring each need their own explicit choice;
a vertical child needs a matching approved baseline crop. Without these options,
keep the existing talking-head/Shorts framing. Normal Watch/transcript/QC and human
approval still apply to the actual rendered output.

| Phase | Action | Reference |
| ----- | ------ | --------- |
| 0 | Confirm overlay vs captions intent | this table |
| 1 | Transcript aligned (`/avo.transcribe` if missing) | [`transcribe.md`](transcribe.md) |
| 2 | Load **`talking-head-recut`** — design cards synced to transcript | `.agents/skills/talking-head-recut/SKILL.md` |
| 3 | watch-skill LOOP + **human approval gate** | [`watch.md`](watch.md) |
| 4 | Optional [`captions.md`](captions.md) if burn-in also needed | after overlays approved |
| 5 | [`rights.md`](rights.md) | required before deliver |
| 6 | [`audio-qc.md`](audio-qc.md) + [`deliver.md`](deliver.md) | master QC |

## Flags

| Flag | Meaning |
| ---- | ------- |
| `--preview` | 360p/720p proofs until approved |
| `--skip-motion` | Stop after edit/transcript — rarely used here |

## Related

- Motion graphics one-off: [`motion-graphics.md`](motion-graphics.md)
- Args: [`arguments.md`](arguments.md)
