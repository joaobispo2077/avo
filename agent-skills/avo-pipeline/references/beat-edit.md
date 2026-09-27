# /avo.beat-edit reference

## Step/state mapping

**Durable state:** the child pipeline-run.json and its parent timeline lineage

**Workflow steps:** Validate beat-edit prerequisites → Map reference or generate from inserts → Verify and report the beat-edit result

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing required input, a failed or stale gate, a required human decision, or verified beat-edit completion

**Valid next commands:** /avo.watch

Profile workflow: map a reference beat-edit, then generate a new HyperFrames edit from a music bed plus operator inserts. Artifacts stay under `<rawDir>/edit/`. Never write into the AVO repo `videos/` folder. Never fork HyperFrames `music-to-video` into git — call its scripts.

## Required args

| Arg | Required | Example |
| --- | -------- | ------- |
| `Provider` | yes | Brand / channel slug |
| `ProjectDir` | yes | Footage root (`rawDir`) |
| `Reference` | map phase | Local reference edit file |
| `Source` | generate phase | Music bed (audio or video-with-audio) |
| `Inserts` | generate phase | Folder of clips / images / GIFs |

## GPU sequence (mandatory)

The resolved transcribe model and the resolved understand model both want the GPU. Run them **one after the other**, never together:

1. Probe + transcribe (`run_job transcribe`) until the subprocess **exits**.
2. Beat grid (`analyze-beatgrid.py`).
3. Stills + closed-vocabulary labels from the resolved understand endpoint.
4. Merge → human map gate.
5. Generate HyperFrames proof.
6. Watch QC (`run_job understand`) on the **proof only**. Watch is not map vision and is not human approval.

## Map phase

1. Confirm `provider` + `rawDir`. Create a **child** timeline with parent lineage (`deliverable.profile` = `beat-edit`).
2. Probe: `python -m avo.beat_edit probe --input <Reference> --edit-dir <rawDir>/edit`
3. Transcribe with project language (do **not** force pt-BR when `transcription.language` is `en` or lyrics are English):

```bash
python -m avo.adapters.run_job transcribe --label local -- <Reference> --edit-dir <rawDir>/edit --language en
```

Or set `AVO_TRANSCRIBE_LANGUAGE` from `avo.project.json` `transcription.language`. Empty transcript is valid (instrumental / slowed-reverb).
4. Beat grid (fail closed if the skill is missing):

```bash
python -m avo.beat_edit grid --audio <audio-or-reference> --edit-dir <rawDir>/edit
```

Writes `edit/audiomap.json` (AUDIOMAP_VERSION 2). If the grid is metronomic, merge records `pacing: phrase_flow`.
5. Stills at audiomap anchors (cap 48), then closed-vocabulary labels — **not** Watch:

```bash
python -m avo.beat_edit stills --input <Reference> --edit-dir <rawDir>/edit
python -m avo.beat_edit vision --edit-dir <rawDir>/edit
```

Vision fails closed when the resolved understand endpoint is unset or unreachable.
6. Merge:

```bash
python -m avo.beat_edit merge --edit-dir <rawDir>/edit --video-id <id> --provider <slug>
python -m avo.beat_edit validate --map <rawDir>/edit/timeline/technique-map.json
```

Canonical files: `edit/timeline/technique-map.json` + `edit/review/technique-map.md`.
7. SOURCE-LOG the reference (timing/moves commentary; reused-content risk). Do not copy reference pixels into the generate inventory by default.
8. Fill `edit/review/approval-gate.md` from `docs/templates/review/approval-gate-manifest.md`. **Stop.** Do not generate until the operator approves the map.

## Generate phase (after map approval)

1. Inventory + assign (recycle in listed order when inserts < events; list leftovers when inserts > events):

```bash
python -m avo.beat_edit inventory --inserts <Inserts>
python -m avo.beat_edit assign --map <rawDir>/edit/timeline/technique-map.json --inventory <inventory.json>
```

Mute insert audio by default. Music bed is the only program audio unless the operator marks a clip keep-source-audio. GIF loops inside the event; stills hold + punch/Ken Burns; video trims to the event.
2. Snap the approved map onto the **new** bed’s audiomap (`python -m avo.beat_edit grid --audio <Source> …` then `snap`). If duration ratio > 1.5, stop and ask for a new map or a loop/trim of the bed.
3. Canvas: match the reference aspect when mapping; otherwise `deliverable.aspect`. Allowed: `1:1`, `9:16`, `16:9`. Cover/crop mismatched inserts; note in review.
4. Author HyperFrames under `<rawDir>/edit/animations/beat-edit/` using the recipes below. Skip a recipe when the map vocabulary marks that id `absent`. Seek-safe GSAP/CSS only (no wall-clock, no unseeded random).
5. Proof name: `YYYYMMDD-beat-edit-proof-v001` under `edit/preview/`. Log every insert + the bed in SOURCE-LOG **before** calling the proof reviewable.
6. Flash check: `python -m avo.beat_edit flash --map …`. Do not reproduce whip flashes denser than 3/s.
7. Watch QC on the proof, then a **second** human gate. Watch pass is not approval.

Generate without a reference: starter map is carousel + punch + caption on project aspect.

## Technique recipes (V1)

| Id | Generate |
| --- | --- |
| `card_carousel` | Row of insert cards; GSAP x-slide; neighbors peek; textured CSS bed |
| `punch_zoom` | Wrapper scale 1 → 1.08–1.2 on the beat; transform only; finite timeline |
| `whip_bump` | Short directional blur + hard swap at peak; skip or lengthen if `flashUnsafe` |
| `kinetic_text` | Overlay from transcript / operator line; caption bar or smash word; provider palette |
| `flip_3d` | CSS/GSAP rotateY 180; if vocabulary is `absent`, do not invent |
| `stylize` | Contrast/posterize **on the insert layer only** |

Load HyperFrames core/animation/creative skills before writing compositions. Brand from `providers/<provider>/DESIGN.md` + `brand/palette.json`.

## Watch vs map vision

| Path | Job | Prompt |
| --- | --- | --- |
| Map labels | `python -m avo.beat_edit vision` | Closed vocabulary on audiomap stills |
| Proof QC | `/avo.watch` / `run_job understand` | Existing Watch pass/fail (maxFrames 18) |

Do not call `WatchSkillAdapter.run()` to label techniques.

## Related

- Args: [`arguments.md`](arguments.md)
- Rights: [`rights.md`](rights.md)
- Watch: [`watch.md`](watch.md)
- Music visualizer (different profile): [`music-video.md`](music-video.md)
