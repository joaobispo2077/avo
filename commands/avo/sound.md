# /avo.sound Command

Audio post: noise reduction, dialogue cleanup, SFX/music mix hierarchy.

**Skill:** [`agent-skills/avo-pipeline/references/sound.md`](../../agent-skills/avo-pipeline/references/sound.md)

For creative SFX generation, use **`/avo.sound create`** mode (see [`sound-create.md`](../../agent-skills/avo-pipeline/references/sound-create.md)).

---

## Usage

```
/avo.sound
Provider: my-channel
rawDir: /path/to/footage
Footage: /path/to/main.mp4
noise-reduction
SFX: /path/to/sfx/
Music: /path/to/music/
```

Modes: `noise-reduction` · `level-match` · `mix` (default when SFX/Music declared)

---

## Role

Apply audio-first rules from `AGENTS.md`: speech intelligibility first, duck music under dialogue, conservative restoration, document changes in `AUDIO-EDITLOG.md` when substantial.

---

## Instructions

1. Parse assets and mode keyword.
2. Diagnose sources (sample rate, channels, clipping, noise) before processing.
3. **Never** destructively overwrite camera originals; work on copies under `edit/`.
4. **Noise reduction (`noise-reduction` mode):**
   - Run `python -m avo.audio_analysis <footage> --suggest-nr [--heatmap]` (see [`noise-reduction-knowledge.md`](../../agent-skills/avo-pipeline/references/noise-reduction-knowledge.md)).
   - Present suggested time ranges and **% strength**; confirm with user before updating EDL.
   - Write `audio.restoration_default_pct` (default 35) and optional `restoration_segments[]`.
   - Segments above **50%** require user approval (`approved_by_user: true`).
5. Mix: dialogue lead → critical source → music → SFX → ambience.
6. Measure loudness; record method in edit log when mastering.
7. Re-sync to picture after audio edits; verify with `ffprobe` and spot-listen.

---

## Example

```text
/avo.sound
Provider: podcast-clips
rawDir: /shows/ep-12
Footage: /shows/ep-12/raw/cam-a.mp4
noise-reduction
Music: /assets/beds/neutral.wav
```
