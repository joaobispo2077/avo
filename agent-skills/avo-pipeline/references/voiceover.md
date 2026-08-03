# /avo.voiceover reference

**Lite voiceover path** — concat B-roll or A-roll clips under an external narration track. Skips HyperFrames/motion by default.

## Preconditions

- [ ] `provider` + `rawDir` declared
- [ ] External voiceover file on disk (WAV/MP3/M4A); script-only noted as BL-003/TTS v2
- [ ] Clip sources inventoried; optional `/avo.sync` for multi-source alignment

## Workflow

1. Build minimal EDL under `<rawDir>/edit/edl.json`:
   - `audio.program_mode`: `external_voiceover`
   - `audio.voiceover_source`: key in `sources` pointing at VO file
   - `motion_policy.enabled`: `false`
   - `ranges`: concat-only cuts (no overlays / SFX in v1)
   - `caption_policy.visual_subtitles`: `false` unless user explicitly wants burn-in
2. Validate: `python -m avo.voiceover edit/edl.json --preflight-only`
3. Draft render (~720p): `python -m avo.render edit/edl.json -o edit/preview/voiceover-draft.mp4 --draft`
4. Agent + user review draft; write [`voiceover-gate.md`](../../../docs/templates/review/voiceover-gate.md) → `<rawDir>/edit/review/voiceover-gate.md`
5. After approval, final render (1080p or source cap) and `/avo.deliver`

## Engine notes

- Segment extract is **video-only**; camera audio is discarded.
- VO track gets conservative speech EQ/NR when `noise_reduction_policy` is `conservative_speech_first`.
- Loudness normalization follows project/EDL loudness profile unless `--no-loudnorm`.

## Distinct from

| Command | Use when |
| ------- | -------- |
| `/avo.talking-head` | Graphic overlays on talking-head packaging |
| `/avo.captions` | Caption/subtitle workflow on existing master |
| `/avo.trim` | Transcribe + cut camera dialogue program |
| `/avo.pipeline` | Full motion + deliver stack |

## Handoff

- [`deliver.md`](deliver.md) — master QC and upload pack
- [`sync.md`](sync.md) — before creative cuts on external/multicam sources
- [`audio-qc.md`](audio-qc.md) — post-mix intelligibility check

## Related

- FR-B3 in [`specs/active/avo-capabilities-roadmap/spec.md`](../../../specs/active/avo-capabilities-roadmap/spec.md)
- BL-012 backlog brief
