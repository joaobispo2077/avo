# /avo.sound Command

**Timeline integration:** Owns

## Workflow guidance

**Workflow steps:** Validate sound prerequisites → Run sound → Verify and report the sound result
**Step state source:** pipeline-run.json plus the current canonical timeline revision
**Stopping conditions:** Missing required input, a failed or stale gate, a required human decision, or verified sound completion
**Valid next commands:** /avo.watch or /avo.audio-qc

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

Audio post: read-only audit, noise reduction, regional gain, dialogue cleanup, SFX/music mix hierarchy.

**Skill:** [`agent-skills/avo-pipeline/references/sound.md`](../../agent-skills/avo-pipeline/references/sound.md)

For creative SFX generation, use **`/avo.sound create`** mode (see [`sound-create.md`](../../agent-skills/avo-pipeline/references/sound-create.md)).

---

## Usage

```
/avo.sound
Provider: my-channel
rawDir: /path/to/footage
Footage: /path/to/main.mp4
audit
```

Modes: `audit` · `noise-reduction` · `level-match` · `mix` (default when SFX/Music declared)

---

## Role

Apply audio-first rules from `AGENTS.md`: speech intelligibility first, duck music under dialogue, conservative restoration, document changes in `AUDIO-EDITLOG.md` when substantial.

---

## Instructions

1. Parse assets and mode keyword.
2. Diagnose sources (sample rate, channels, clipping, noise) before processing.
3. **Never** destructively overwrite camera originals; work on copies under `edit/`.
4. **Audit (`audit` mode)** — read-only evaluation before any render:

   ```bash
   python -m avo.audio_audit <footage> --project avo.project.json --transcript edit/transcripts/<base>.json --out-dir edit/review
   ```

   Present `audio-audit.json` to the user. Nothing is modified. Use `--strict` when loudness must pass ±2 LU.

5. **Noise reduction (`noise-reduction` mode):**
   - Run `python -m avo.audio_analysis <footage> --suggest-nr [--heatmap]` (see [`noise-reduction-knowledge.md`](../../agent-skills/avo-pipeline/references/noise-reduction-knowledge.md)).
   - Present suggested time ranges and **% strength**; confirm with user before updating EDL.
   - Write `audio.restoration_default_pct` (default 35) and optional `restoration_segments[]`.
   - Segments above **50%** require user approval (`approved_by_user: true`).

6. **Level-match (`level-match` mode):**
   - Run `python -m avo.audio_analysis <footage> --suggest-gain --transcript …` (see [`gain-knowledge.md`](../../agent-skills/avo-pipeline/references/gain-knowledge.md)).
   - Preview with `--preview-gain-segment START END --boost-pct N`.
   - Persist `audio.gain_segments[]`; segments above **40%** require approval.

7. Mix: dialogue lead → critical source → music → SFX → ambience.
8. Measure loudness; record method in edit log when mastering.
9. Re-sync to picture after audio edits; verify with `ffprobe` and spot-listen.

---

## Example

```text
/avo.sound
Provider: podcast-clips
rawDir: /shows/ep-12
Footage: /shows/ep-12/raw/cam-a.mp4
audit
Transcript: /shows/ep-12/edit/transcripts/cam-a.json
```

## Canonical track integration

Owns ordered audioTracks layers and BMap audio cues against the exact approved CMap output. Changes stale audio/composite Watch and QC evidence. Dialogue remains centered and leading; music/SFX expose gains, fades, ducking, channels, mute, and loudness intent.

## Shared timeline gateway

Uses shared timeline storage, transition guards, invalidation, and AI review services. It cannot maintain private CMap, BMap, sync, track, animation, or approval truth.
