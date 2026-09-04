# /avo.podcast-clip reference

## Step/state mapping

**Durable state:** the child pipeline-run.json and its parent timeline lineage

**Workflow steps:** Validate podcast clip prerequisites → Run podcast clip → Verify and report the podcast clip result

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing required input, a failed or stale gate, a required human decision, or verified podcast clip completion

**Valid next commands:** /avo.watch

**Orchestrator** for podcast / interview clip extraction. Distinct from [`shorts.md`](shorts.md) (Shorts shelf) and [`guidelines-podcast.md`](guidelines-podcast.md) (Phase 0 diagnosis only).

## Phase 0 — Diagnosis

Load [`guidelines-podcast.md`](guidelines-podcast.md). Record clip promise, speaker context, rights posture, segment bounds.

## Flags

| Flag | Default | Meaning |
| ---- | ------- | ------- |
| `--max-duration N` | none | Warn/block promotion over N seconds without EDITLOG override |
| `--identity NAME` | — | Pass to `/avo.captions` when captions requested |
| `--vertical` | off | Delegate to [`reframe.md`](reframe.md) for 9:16 from long-form master |
| `--skip-motion` | off | Skip motion phase |
| `--preview` | on | Stay on 360p/720p until approved |

See [`arguments.md`](arguments.md).

## Workflow phases

| Phase | Action | Reference |
| ----- | ------ | --------- |
| 0 | Podcast clip diagnosis | [`guidelines-podcast.md`](guidelines-podcast.md) |
| 1 | Segment select (`from`/`to` or anchors) | user + transcript |
| 2 | Trim + watch-skill LOOP + **human approval gate** | [`trim.md`](trim.md), [`watch.md`](watch.md) |
| 3 | Optional captions when `identity` provided | [`captions.md`](captions.md) |
| 4 | **Required** rights audit | [`rights.md`](rights.md) |
| 5 | **Required** audio delivery QC | [`audio-qc.md`](audio-qc.md) |
| 6 | Deliver with `podcast-clip` profile | [`deliver.md`](deliver.md) |

## Branch: `--vertical`

1. Confirm approved long-form master exists.
2. Run [`reframe.md`](reframe.md) for segment → vertical intermediate.
3. Continue phases 3–6 on reframed working footage.

## Manifest hints

```json
"deliverable": {
  "profile": "podcast-clip",
  "aspect": "16:9",
  "maxDurationSec": null
}
```

## Related

- Delivery spec: [`docs/delivery-specifications.md`](../../../docs/delivery-specifications.md)
- Shorts orchestrator: [`shorts.md`](shorts.md)
