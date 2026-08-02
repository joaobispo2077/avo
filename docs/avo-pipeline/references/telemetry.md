# /avo.telemetry reference

Implements [`docs/avo-workflow.md`](../../avo-workflow.md) §5.

## Required fields

| Field | Source |
| ----- | ------ |
| disk free | Volume hosting `rawDir` |
| step bytes | Bytes created since last telemetry call |
| project bytes | Total under `<rawDir>/edit/` (+ declared assets if counted) |
| phase n / total | User or inferred from pipeline stage |
| pct | `round(n/total*100)` |
| eta rough | Elapsed / n * (total-n); label as estimate |

## Canonical output

**Human line (illustrative):**

```text
[phase 4/6 · motion-proof 720p] disk free 812.4 GB · step +1.9 GB · project 6.3 GB · 66% · ~4m left (rough)
```

**JSON line (illustrative):**

```json
{"phase":"motion-proof","n":4,"total":6,"pct":66,"diskFreeBytes":872000000000,"stepBytes":1900000000,"projectBytes":6300000000,"etaSeconds":240,"etaRough":true,"activeModels":{"transcribe":"faster-whisper:small","understand":"Qwen 2.5 7B","plan":"Qwen 2.5 7B"}}
```

| Field | Source |
| ----- | ------ |
| `activeModels` | `helpers.models.resolve_active_models()` (catalog + config + state + project) |

Human lines may append `| models transcribe=faster-whisper:small, understand=…` when models resolve.

## Hardware advisory (optional)

On render/watch phases, also run `src/avo/hardware.py` and summarize tier recommendation in prose (advisory only, never blocks).

## Roll-up

Persist summary lines to `.avo/state.json` when project state file exists (no secrets).
