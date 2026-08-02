# /avo.sound reference

Follow [`AGENTS.md`](../../../AGENTS.md) audio rules and [`docs/audio-post-production-system.md`](../../audio-post-production-system.md).

**Boundary:** mix, restoration, and hierarchy here; **delivery loudness / true peak QC** on the approved master → [`/avo.audio-qc`](audio-qc.md).

## Modes

| Keyword | Action |
| ------- | ------ |
| `noise-reduction` | Spectral/waveform targeted NR; conservative |
| `level-match` | Gain-stage clips before mix |
| `mix` | Full hierarchy with declared SFX/Music |

## Helpers

Use ffmpeg filters and project audio helpers. Log substantial work to `AUDIO-EDITLOG.md`.

## `/avo.sound create`

See [`sound-create.md`](sound-create.md) for designed SFX (NS2-style cinematic briefs).
