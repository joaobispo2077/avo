# /avo.pipeline Command

Run the full AVO pipeline from declared assets through deliver.

**Skill:** [`agent-skills/avo-pipeline/references/pipeline.md`](../../agent-skills/avo-pipeline/references/pipeline.md)

**See also:** [`docs/avo-workflow.md`](../../docs/avo-workflow.md) · [`SKILL.md`](../../SKILL.md)

---

## Usage

```
/avo.pipeline
Provider: my-channel
rawDir: /path/to/footage
Footage: /path/to/main.mp4
SFX: /path/to/sfx/
B-roll: /path/to/broll/
Music: /path/to/music/
```

Optional: `--skip-motion`, `--preview`, `--lang pt`

---

## Role

Orchestrate stages 0–7: plan (optional Spec Kit) → transcribe → edit → watch-skill LOOP → **human approval** → motion (unless skipped) → render → deliver → cleanup.

---

## Instructions

1. **Parse inputs** per [`arguments.md`](../../agent-skills/avo-pipeline/references/arguments.md).
2. **Resolve provider** manifest: `providers/<provider>/avo.provider.json`.
3. **Write or update** `<rawDir>/avo.project.json` with asset paths.
4. **Start session (REQUIRED):** run `python -m avo.session start --raw-dir <rawDir> --provider <provider> [--title TEXT]` — writes `.avo/sessions/<id>/pre.json` baseline inventory for wrap diff and stats.
5. **Inventory** sources (`ffprobe`), transcribe, pack transcripts.
6. **Converse** → propose strategy → **wait for confirmation**.
7. **Execute** edit proof (~360p) → watch-skill LOOP → write `edit/review/edit-proof/approval-gate.md` → **wait for approval**.
8. Unless `--skip-motion`: motion proof (~720p) → LOOP → approval gate → promote to source resolution.
9. **Deliver** master + final transcript; run `/avo.learndown` then `/avo.cleanup` per preserved-set rules (§7).

Report telemetry at each phase boundary (disk, progress, ETA estimate). Pass `session_id` when telemetry helper supports it.

---

## Example

```text
/avo.pipeline
Provider: auto-lot
rawDir: H:/footage/dealer-walk
Footage: H:/footage/dealer-walk/raw/walkthrough.mp4
Music: H:/assets/music/soft-bed.wav
```
