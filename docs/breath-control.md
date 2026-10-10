# Opt-in dialogue breath control

Breath control is **off by default**. Activate only on an explicit request.
An unspecified request to reduce breathing means conservative attenuation,
not muting, cutting pauses, gating the microphone or processing the master.
It is editorial cleanup, not a diagnosis of the presenter's health.

## Independent decisions

Choose an action and a selection separately. Every selected event must have
reviewed boundaries, source fingerprints and protected-word evidence.

| Action | Result | Timeline duration |
| --- | --- | --- |
| `preserve` | Keep all breathing | Unchanged |
| `attenuate` | Reduce toward a level relative to nearby speech, never boost | Unchanged |
| `fixed` | Reduce by a specified gain | Unchanged |
| `room-tone` | Replace confirmed isolated breaths with approved room tone | Unchanged |
| `shorten` | Propose removal of the middle of a breath, retaining a pause | Changes only after CMap approval |
| `cut` | Propose removal of the selected breath interval | Changes only after CMap approval |
| `hybrid` | Propose shortening long events; attenuate residual/short events in a separately reviewed gain pass | Changes only after CMap approval |

| Selection | Use |
| --- | --- |
| `all` | All **confirmed breathing**, not all non-speech sound |
| `long` | Only breaths at or above the duration threshold |
| `heavy` | Only breaths above the relative loudness threshold |
| `long-or-heavy` | Either threshold is met |
| `long-and-heavy` | Both thresholds are met |
| `manual` | Specifically marked events, including exceptions by speaker/section |

Common combinations include natural interviews with no treatment; gentle
attenuation throughout a talking head; strong reduction of heavy breathing;
shortening only long inhalations; replacing isolated breaths while retaining
pauses; trimming all confirmed breathing for a tightly paced voice-over; and
hybrid shortening plus reduction. Preserve expressive sighs, laughter, effort,
singing and dramatic timing by default. Per-speaker policies require separate
dialogue anchors or individually reviewed events. Overlapping speech is not an
automatic candidate. "All" is not a guarantee of detection coverage.

## Defaults and limits

- Conservative reduction: target 20 dB below adjacent speech, maximum 9 dB.
- Fixed reduction: 6 dB, still bounded by the maximum.
- Long: 600 ms. Heavy: within 15 dB of nearby speech RMS.
- Protect each word plus 80 ms on each side; widen when alignment is uncertain.
- Smooth gain edges: 30 ms down, 50 ms up, unity at the endpoints.
- Shortening retains a nominal 250 ms pause, subject to editorial approval.

These are tunable starting points, not universal acoustic standards. Strong
attenuation may leave a noise-floor dip; back off or use genuine room tone.
Near-inaudibility is a listening goal, not a guarantee on every device.
Do not lower the spoken phrase to conceal a breath.

## Source and detection workflow

1. Inventory microphone, product, gameplay, music and SFX sources. A microphone
   may contain product clicks or game audio even if its role is dialogue.
2. Verify raw-source lineage and the current CMap/EDL projection. A cached word
   transcript must match the **actual** dialogue sample clock. Different source
   and program durations are a warning; do not assume a linear offset repairs it.
3. Audit the unmixed dialogue with local waveform analysis and guarded words.
   The installed heuristic proposes pauses/noise-like events. It does not certify
   breaths: all proposals remain `ambiguous` until listening/annotation.
   Fricatives, inhalations during words, coughs, handling and untranscribed speech
   need manual inspection. No detector/model is installed automatically.
4. Mark actual breaths `confirmed` or import validated `safe` annotations.
   Reject other sounds and protect expressive events. Inspect gaps not detected
   by the heuristic; low recall is preferable to clipping a word.
   A creator's rounded timestamp identifies an area to inspect, not the exact
   extent of a breath. Expanding it to a nearby transcript gap can remove speech
   omitted or mistimed by ASR. Refine each boundary against the actual dialogue
   waveform/spectrum and retain the creator's original timebase. Record inspected
   speech regions separately; an ASR word can incorrectly include a whole breath,
   while an ASR gap can contain a spoken word. Fresh local ASR can corroborate
   the inspection but does not itself certify the boundaries.
5. Generate before/after and removed-signal previews. Listen to what was removed:
   any consonant, vowel, product or gameplay sound fails the pass.
6. Approve the preview, then author a new Tracks revision through normal services.
   Breathing metadata lives on `audioTracks.layers[].breathControl`; standalone
   review drafts never overwrite canonical revisions.

Commands, with all paths resolved to the external footage project:

```text
python -m avo.cli breathing audit --project <avo.project.json> --source <dialogue> --transcript <words.json> --raw-source-id <source-id> --out-dir <edit/review/new-audit>
python -m avo.cli breathing review --project <avo.project.json> --source <dialogue> --analysis <audit/manifest.json> --limit 12 --out-dir <edit/review/new-listening>
python -m avo.cli breathing preview --project <avo.project.json> --source <dialogue> --transcript <words.json> --control <reviewed-control.json> --from <seconds> --to <seconds> --out-dir <edit/review/new-preview>
python -m avo.cli breathing apply --project <avo.project.json> --source <dialogue> --transcript <words.json> --control <reviewed-control.json> --out-dir <edit/audio/new-dialogue>
python -m avo.cli breathing propose-cuts --project <avo.project.json> --source <dialogue> --transcript <words.json> --control <reviewed-control.json> --out-dir <edit/review/new-cut-proposals>
```

When using raw word times for processing, include `--raw-source-id` and the
current EDL SHA-256 as `projectionSha256`. Enabled controls require the dialogue
and transcript SHA-256, sample rate, events and protected ranges. The CLI adds
word protection again; it cannot be disabled by an empty protection list.
Output versions are immutable. `apply` produces a dialogue derivative, not an
approval, master, normalization pass or canonical Tracks mutation.
`review` creates untreated excerpts plus an event cue sheet for classification.
It applies only 10 ms excerpt-edge fades and cannot approve breathing treatment.
A raw word projection whose duration differs by more than one nominal 30 fps
frame from the dialogue is blocked for processing. Diagnose accumulated padding
or drift; do not disguise it with a single offset or erase the warning.

## Strict isolation in the mix

Never run breath reduction on the combined program. Music and SFX do not pass
through the gain envelope. With dynamic music ducking, freeze the original mix
**before** breathing treatment and subtract only the sample-domain dialogue
delta. This keeps the original sidechain behavior rather than allowing quieter
breaths to make music rise. The renderer's two-pass materializer fingerprints
its canonical inputs and saves a manifest and float PCM baseline.

Outside selected events, samples must be bit-identical. Within them, the only
change is the dialogue delta, to floating-point tolerance. The baseline must be
reconstructed from current canonical sources, never an approved proof/master.
The live graph compiler rejects breath processing with dynamic ducking; callers
must use frozen materialization. The initial materializer supports one full-
program dialogue anchor. Multiple simultaneous anchors and room-tone mixing
must be materialized explicitly, not silently approximated.

Normalization follows correction. For an approval comparison use the same gain
and limiter settings on before/after. Independently renormalizing the quieter
version can raise the entire program and defeat the isolation requirement.
No new automatic whole-program level adjustment is introduced by this feature.

## Trimming is a picture edit

`propose-cuts` emits raw-source anchors, never audio-only deletions. Review frame
snapping, word margins, lip sync, pause meaning and room tone. Approved changes
go through CMap authoring, then BMap/Tracks/Animation/Sync projection and normal
invalidation. Rebuild captions and remap cues. Shorten/cut/hybrid are blocked in
the gain-only processor until this editorial workflow is complete.

## QC and rollout

- Verify unchanged sample count, channels and 48 kHz timing for gain-only passes.
- Null-test untreated samples and frozen non-dialogue contribution.
- Compare whole words at fixed loudness; no lost starts, ends or fricatives.
- A null test outside declared events proves isolation, not that those events
  contain only breaths. When a reviewer reports ducked speech, invalidate the
  affected boundary evidence and restore the spoken regions. Do not merely
  increase attenuation or retain other gap-derived events without inspection.
  A periodicity check can flag voiced material in a proposed removal, but passing
  it does not certify unvoiced consonants, handling sounds or expressive breaths.
- Listen to original, processed and removed signal on headphones and speakers;
  phone-style listening is supplemental, not a substitute for actual devices.
- No clicks, pumping, artificial silence, altered emotion or hidden source cues.
- Full-program loudness and true peak are checked after encode, with human review.
- Record policy, thresholds, rejected/protected events, source hashes and decision
  in AUDIO-EDITLOG.md. Preserve approved exports. New 4K renders require approval.

## Research basis

[iZotope Breath Control](https://downloads.izotope.com/docs/rx6/18-breath-control/index.html)
documents fixed gain versus target-level reduction and breath-only monitoring.
[Waves DeBreath](https://assets.wavescdn.com/pdf/plugins/debreath.pdf)
describes voice/breath separation, fades, monitoring and background fill.
[Breath detection research](https://arxiv.org/html/2402.00288v2) illustrates the
precision/recall tradeoff of acoustic features; results on clean English speech
are not validation on a Portuguese review with handling and gameplay sounds.
[FFmpeg audio filters](https://ffmpeg.org/ffmpeg-filters.html) support sample gain
and fades, but an amplitude gate or silence detector alone is not a breath
classifier. These references justify conservative event-based editing, not
universal threshold settings.
