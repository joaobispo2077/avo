# /avo.trailer reference

**Orchestrator** for program teaser / trailer cuts from an approved long-form master.

## Phase 0 — Diagnosis

Load skill **`retention-diagnostics`** + format diagnosis:

| Field | Record |
| ----- | ------ |
| Viewer promise | what the trailer may preview vs withhold |
| Target duration | default **90s** (`--max-duration`) |
| Misleading preview risk | events shown must occur in full program |
| Rights posture | music, clips, archive in teaser segments |

**Forbidden:** empty cliffhangers, previews of scenes that do not occur, manufactured tension unsupported by source.

## Flags

| Flag | Default | Meaning |
| ---- | ------- | ------- |
| `--max-duration N` | 90 | Target teaser length; warn if structural trim needed |
| `--preview` | on | Stay on 360p/720p proofs until approved |

See [`arguments.md`](arguments.md).

## Workflow phases

| Phase | Action | Reference |
| ----- | ------ | --------- |
| 0 | Retention + format diagnosis | `retention-diagnostics` |
| 1 | Select teaser segments from approved master | transcript + structure |
| 2 | Trim + watch-skill LOOP + **human approval gate** | [`trim.md`](trim.md), [`watch.md`](watch.md) |
| 3 | **Required** rights audit | [`rights.md`](rights.md) |
| 4 | **Required** audio QC + deliver (`trailer` profile) | [`audio-qc.md`](audio-qc.md), [`deliver.md`](deliver.md) |

## Manifest hints

```json
"deliverable": {
  "profile": "trailer",
  "maxDurationSec": 90,
  "aspect": "16:9"
}
```

## Related

- Retention diagnosis (on-demand): `/avo.retention` when shipped
- Deliver spec: [`docs/delivery-specifications.md`](../../../docs/delivery-specifications.md)
