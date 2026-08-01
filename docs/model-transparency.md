# Model transparency

AVO surfaces **which models** run for each job, how heavy they are, and what
lighter/heavier alternatives exist — in setup, phase telemetry, and agent prose.

## Sources of truth

| Layer | File | Role |
| --- | --- | --- |
| Catalog | [`avo.model-catalog.json`](../avo.model-catalog.json) | All options + VRAM/RAM/disk/speed/quality |
| Defaults | [`avo.config.json`](../avo.config.json) `models` | Orchestrator defaults |
| Runtime | `.avo/state.json` | Setup-persisted whisper size + optional LLM tiers |
| Project | `avo.project.json` | Per-video overrides (`transcription.model`, `models.*`) |
| Advisory | [`helpers/hardware.py`](../helpers/hardware.py) | Suggested tiers from CPU/GPU/RAM |

## Resolver

```bash
python helpers/models_cli.py show
python helpers/models_cli.py alternatives transcribe
python helpers/models_cli.py disclosure
```

Programmatic: `helpers.models.resolve_active_models()`, `list_alternatives(job)`.

## Telemetry

Phase JSON (stderr `AVO_JSON`) includes `activeModels`:

```json
{
  "phase": "transcribe",
  "activeModels": {
    "transcribe": "faster-whisper:small",
    "understand": "Qwen 2.5 7B",
    "plan": "Qwen 2.5 7B"
  }
}
```

## Agent transparency template

> Detected: `<CPU>`, `<RAM>`, GPU `<name>`. **Transcribe:** `faster-whisper/<size>`
> (~`<disk>` disk, ~`<vram>` VRAM). **Understand:** `<qwen tier>` (watch-skill).
> Lighter: `<tier>` (faster). Heavier: `<tier>` (better quality). Advisory only —
> say the word to change tiers.

Load alternatives from `python helpers/models_cli.py alternatives <job> --json`.

## Swapping models

| Job | How to change |
| --- | --- |
| Transcribe (local) | Re-run setup with `--model medium`, or set `avo.project.json` → `transcription.model` |
| Understand / plan | Set `.avo/state.json` → `models.understand` / `models.plan`, or project `models.*` |
| Paid transcribe | `avo.config.json` `models.transcribe_paid`; requires `ELEVENLABS_API_KEY` |

See [`docs/adapters.md`](adapters.md) for port/adapter boundaries.
