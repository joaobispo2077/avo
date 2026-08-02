# /avo.shorts reference

**Orchestrator** for YouTube Shorts (vertical ≤60s shelf intent). Distinct from [`guidelines-shorts.md`](guidelines-shorts.md) (`/avo.guidelines --shorts` = diagnosis only).

## Phase 0 — Diagnosis

Load [`guidelines-shorts.md`](guidelines-shorts.md) checklist. Record in project notes or `avo.project.json`:

**HyperFrames motion (phase 3):** when not `--skip-motion`, load [`short-form-knowledge.md`](short-form-knowledge.md) before authoring 9:16 overlay slots — scaffold, face-mode, edited-time sync.

| Field | Values |
| ----- | ------ |
| Mode | `native` (vertical source) \| `from-master` (extract + reframe) |
| Viewer promise | hook + payoff |
| Rights posture | music, clips, reused-content |
| Caption intent | identity if known |

## Flags

| Flag | Default | Meaning |
| ---- | ------- | ------- |
| `--from-master` | off | Delegate to [`reframe.md`](reframe.md) before captions/deliver |
| `--max-duration N` | 60 | Warn + block promotion over N seconds without EDITLOG override |
| `--skip-motion` | off | Skip motion phase |
| `--identity NAME` | — | Pass to `/avo.captions` |
| `--preview` | on | Stay on 360p/720p until approved |

See [`arguments.md`](arguments.md).

## Workflow phases

| Phase | Action | Reference |
| ----- | ------ | --------- |
| 0 | Shorts diagnosis | [`guidelines-shorts.md`](guidelines-shorts.md) |
| 1 | Trim + transcribe semantics | [`trim.md`](trim.md) — note 9:16 safe margins in manifest |
| 2 | watch-skill LOOP + **human approval gate** | [`watch.md`](watch.md) |
| 3 | Optional motion (Level 2–3 cap when text readable) | [`motion.md`](motion.md) + [`short-form-knowledge.md`](short-form-knowledge.md) — skip with `--skip-motion` |
| 4 | Captions when `identity` provided or user requests | [`captions.md`](captions.md) |
| 5 | Duration check (`ffprobe`); enforce `--max-duration` | block promotion without EDITLOG override |
| 6 | Full master QC + manifest | [`deliver.md`](deliver.md) with Short profile |

## Branch: `--from-master`

1. Confirm approved long-form master exists.
2. User supplies `from`/`to` or phrase anchors.
3. Run [`reframe.md`](reframe.md) workflow → vertical intermediate.
4. Set reframed file as working `Footage` for phases 4–6.

## Duration policy

- Default max: **60 seconds** for Shorts shelf intent
- If export > `--max-duration`: **warn** user; **block** promotion to master without explicit override documented in `EDITLOG.md` or project notes
- Do not silently trim to fit — user must approve structural change

## Manifest hints

```json
"deliverable": {
  "profile": "shorts",
  "maxDurationSec": 60,
  "aspect": "9:16"
}
```

## Escape hatch

Low-level manual chain still valid: `/avo.trim` + `/avo.motion` + `/avo.captions` + `/avo.deliver`. Prefer `/avo.shorts` for consistent gates and duration checks.

## Related

- TikTok vertical (different playbook): `/avo.guidelines --tiktok`
- Reframe only: [`reframe.md`](reframe.md)
- Delivery template: [`docs/templates/delivery/delivery-manifest.md`](../../../docs/templates/delivery/delivery-manifest.md)
