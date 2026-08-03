# /avo.sound reference

Follow [`AGENTS.md`](../../../AGENTS.md) audio rules and [`docs/audio-post-production-system.md`](../../audio-post-production-system.md).

**Boundary:** mix, restoration, and hierarchy here; **delivery loudness / true peak QC** on the approved master → [`/avo.audio-qc`](audio-qc.md).

## Modes

| Keyword | Action |
| ------- | ------ |
| `audit` | Read-only loudness + NR + EQ + gain report — **no media changes** (see below) |
| `noise-reduction` | Analyze waveform → suggest % per region → user confirms → EDL `restoration_segments[]` (see [`noise-reduction-knowledge.md`](noise-reduction-knowledge.md)) |
| `level-match` | Analyze quiet dialogue → suggest boost % → preview → EDL `gain_segments[]` (see [`gain-knowledge.md`](gain-knowledge.md)) |
| `mix` | Full hierarchy with declared SFX/Music |

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
