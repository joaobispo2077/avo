# /avo.sound reference

Follow [`AGENTS.md`](../../../AGENTS.md) audio rules and [`docs/audio-post-production-system.md`](../../audio-post-production-system.md).

**Boundary:** mix, restoration, and hierarchy here; **delivery loudness / true peak QC** on the approved master → [`/avo.audio-qc`](audio-qc.md).

## Modes

| Keyword | Action |
| ------- | ------ |
| `noise-reduction` | Analyze waveform → suggest % per region → user confirms → EDL `restoration_segments[]` (see [`noise-reduction-knowledge.md`](noise-reduction-knowledge.md)) |
| `level-match` | Gain-stage clips before mix |
| `mix` | Full hierarchy with declared SFX/Music |

## Helpers

Use ffmpeg filters and project audio helpers. Log substantial work to `AUDIO-EDITLOG.md`.

## `/avo.sound create`

See [`sound-create.md`](sound-create.md) for designed SFX (NS2-style cinematic briefs).
