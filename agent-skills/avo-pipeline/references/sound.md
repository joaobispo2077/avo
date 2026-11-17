# /avo.sound reference

Waveform caches retain reusable measurements, not manual marker review decisions.
Identical PCM and marker positions can reuse analysis while a changed review flag
changes the current disposition. A transient analysis pass does not approve the
sound choice, contextual mix, rights or finished video. Catalogue marker/rights
reviews remain separately source-bound curated records.

## Step/state mapping

**Durable state:** pipeline-run.json plus the current canonical timeline revision

**Workflow steps:** Validate sound prerequisites → Run sound → Verify and report the sound result

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing required input, a failed or stale gate, a required human decision, or verified sound completion

**Valid next commands:** /avo.watch or /avo.audio-qc

Follow [`AGENTS.md`](../../../AGENTS.md) audio rules and [`docs/audio-post-production-system.md`](../../audio-post-production-system.md).

**Boundary:** mix, restoration, and hierarchy here; **delivery loudness / true peak QC** on the approved master → [`/avo.audio-qc`](audio-qc.md).

## Modes

| Keyword | Action |
| ------- | ------ |
| `audit` | Read-only loudness + NR + EQ + gain report — **no media changes** (see below) |
| `noise-reduction` | Analyze waveform → suggest % per region → user confirms → EDL `restoration_segments[]` (see [`noise-reduction-knowledge.md`](noise-reduction-knowledge.md)) |
| `level-match` | Analyze quiet dialogue → suggest boost % → preview → EDL `gain_segments[]` (see [`gain-knowledge.md`](gain-knowledge.md)) |
| `mix` | Full hierarchy with declared SFX/Music |
| `breathing` | Explicit opt-in dialogue breath audit and reviewed gain-only treatment; see [breathing guidelines](guidelines-breathing.md) |

## Read-only audit (`audit` mode)

Run before committing to edits:

```bash
python -m avo.audio_audit <footage> --project avo.project.json --transcript edit/transcripts/<base>.json --out-dir edit/review
```

- Writes `audio-audit.json` with `loudness`, `noise_reduction`, `eq`, `gain`, and `warnings`.
- Never modifies source or master.
- Add `--strict` to exit 2 when integrated loudness is outside target ±2 LU.

Individual checks:

| Check | Command |
|-------|---------|
| Loudness only | `python -m avo.audio_analysis <footage> --measure-loudness --project avo.project.json` |
| NR suggest | `python -m avo.audio_analysis <footage> --suggest-nr --heatmap` |
| EQ suggest | `python -m avo.audio_analysis <footage> --suggest-eq --eq-heatmap` |
| Gain suggest | `python -m avo.audio_analysis <footage> --suggest-gain --transcript …` |

See [`eq-knowledge.md`](eq-knowledge.md) and [`gain-knowledge.md`](gain-knowledge.md).

## Pipeline order (apply phase)

```
regional gain (approved gain_segments)
  → EQ/NR on segment extract
  → mix/composite
  → loudnorm (resolved profile)
```

## Helpers

Use ffmpeg filters and project audio helpers. Log substantial work to `AUDIO-EDITLOG.md`.

## `/avo.sound create`

See [`sound-create.md`](sound-create.md) for designed SFX (NS2-style cinematic briefs).

## Canonical track integration

For optional SFX discovery, first use the saved local catalogue through
`sfx show/search`. [Media discovery](media.md#local-sound-discovery) defines bounded
scan/annotation requests, generation conflicts, rights, favorites and audition
ranges. Descriptor search is metadata-only; `search-semantic` explicitly executes
separately provisioned local models. Missing semantic readiness does not silently
switch modes. A matching preference or result never starts playback, remixes the
film, adds an effect or grants BMap/Tracks approval. Silence/no-match is valid.

Review a sound's useful range and actual perceptual anchor by listening. Cached
waveform peaks alone cannot establish that review. Preserve dialogue priority,
original channel intent and current cut/source identity when a later selected
sound is authored through the existing normal owners and proof pipeline.

### Event-bound sound proposals

Use `avo cli sfx propose --project <absolute avo.project.json> --video-id <id> --request <absolute request.json> --json`
(checkout: `python -m avo.cli`). The native command and `avo_sfx_propose` accept
the same strict `avo.sound-selection.schema.json#/$defs/proposeRequest` document.
Supply the current `expectedBasis` heads, `expectedGeneration`, exact output
`clock`, resolved editing-craft `selection`, and bounded `intents`. Sound matching
must be explicitly enabled; an active request retains its original options until
an explicit new request is selected.

Each intent identifies a stable `eventId`, current motion `itemId`, purpose,
role, declared visibility and motion character. An optional `cueId` resolves
split items; `phase` locates an accent inside the canonical cue. Missing,
ambiguous or removed anchors remain unresolved. Slow, hidden, static and
background movement recommend silence. Silence is always available and no
effect is added merely because motion exists.

Proposals save immutable metadata under `edit/motion/sound/`, binding current
heads, selected sound direction, options, library generation, queries and actual
bounded search results. Repeating the same operation returns its saved proposal;
reuse of an operation ID with changed inputs fails. Candidate budgets and missing
queries are explicit. The command does not scan sources, provision or start a
semantic model; an unavailable selected semantic mode stays unavailable. These
proposals do not publish BMap/Tracks, start playback or grant listening approval.

The fitting primitive uses the original reviewed source-sample marker minus the
explicit trim start. Its duration follows the existing native audio boundaries,
including resampling rounding, and preserves useful attacks and tails. A fit
still requires current source/rights checks, canonical publication and contextual
listening. Draft proposals are not selected reconstruction evidence.

Per-event choice preparation freezes the full supplied entry, reviewed marker,
fitted schedule, explicit channel map, gain, fades and ducking request. Its pure
API does not validate live source bytes or catalogue membership; the publishing
caller must bind those checks to current heads. Existing ordinary-overlay entry
limits still apply to main/bass/support/detail/tail roles. Multiple layers need
an exact ordered event list, and main-scene synthetic effects need an explicit
disposition. Comparison-only references cannot supply published sound.

Choice preparation checks measured channel count, the explicitly selected source
peak ceiling, and fade space outside the useful attack/tail. It does not invent a
gain target or change the original dialogue/music. Repeated sources and coincident
attacks are advisories. Per-ID changes report before/after asset identities, role,
gain and schedule; live source checks, combined peak, speech masking and actual
contextual listening remain review obligations. This API does not yet publish
canonical audio.

The native proof graph compiler can qualify frozen choices using the existing
source-native audio path. It keeps the full program clock during window renders,
emits one contribution per stable event, and rejects conflicting replay, source
fingerprints or program mix policies. Ducking requires an explicit mapping to
current dialogue nodes. It does not choose a dialogue replacement or process the
original music. Canonical source/catalogue/head admission and selected evidence
retention still belong to the forthcoming sound publication route.

Selected sound track metadata now has an explicit reader contract. A published
selection requires a version 2 Tracks index with `sound-selection-v1`; ordinary
legacy reads keep version 1. The record binds the frozen source/choice, native
sample region, channel map, level, owning cue and exact proposal/application
references. Readers reject changed or duplicate contributions. Legacy audio
projection rejects this contract because it cannot preserve the selected native
trim. These checks do not admit media, approve a mix or authorize publication.

Inspect audioTracks before render: dialogue priority and channel mapping, music/SFX purpose, source fingerprint, regions, gains, fades, ducking, mute, loudness intent, and BMap cue links. Audio changes invalidate candidate-bound audio and composite evidence.

## Selected artistic guidance

Before style-dependent authoring, run the shared native pipeline status for this project (checkout: `python -m avo.cli pipeline status --project <project> --json`; installed: `avo cli pipeline status --project <project> --json`). Read `briefing.stageContexts.sound` and its exact selected brief, treatment, constraints, exclusions and current canonical-head identities. Treat this context as offered guidance, never proof that a choice was applied, an approval, or permission to change protected content. Current creator instructions and integrity/accessibility/rights rules take precedence. A bypassed or unselected brief adds no creative gate. Do not discover provider history or select a latest profile independently. See [briefstart](briefstart.md).
