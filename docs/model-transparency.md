# Model transparency

AVO surfaces **which models** run for each job, how heavy they are, and what
lighter/heavier alternatives exist — in setup, phase telemetry, and agent prose.

## Sources of truth

| Layer | File | Role |
| --- | --- | --- |
| Catalog | [`avo.model-catalog.json`](../config/avo.model-catalog.json) | All options + VRAM/RAM/disk/speed/quality |
| Defaults | [`avo.config.json`](../config/avo.config.json) `models` | Orchestrator defaults |
| Runtime | `.avo/state.json` | Setup-persisted whisper size + optional LLM tiers |
| Project | `avo.project.json` | Per-video overrides (`transcription.model`, `models.*`) |
| Advisory | [`src/avo/hardware.py`](../helpers/hardware.py) | Suggested tiers from CPU/GPU/RAM |

## Resolver

```bash
python -m avo.models_cli show
python -m avo.models_cli alternatives transcribe
python -m avo.models_cli disclosure
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
> (~`<disk>` disk, ~`<vram>` VRAM). **Understand:** `<understand label>` (watch-skill).
> Lighter: `<tier>` (faster). Heavier: `<tier>` (better quality). Advisory only —
> say the word to change tiers.

`<understand label>` is the catalog label for the resolved understand option — usually
`Qwen 2.5 7B`, or a pinned Bonsai label when `models.understand` is set. Default
transcribe / Qwen examples still apply when nothing is pinned.

Load alternatives from `python -m avo.models_cli alternatives <job> --json`.

## Optional understand: Bonsai 27B GGUF

Understand-only (watch-skill / THE LOOP). The default remains **`qwen2.5-7b`**.
Do not change plan or replace the Qwen default story — pin Bonsai only when you
want 27B-class Watch quality on ~8–12 GB NVIDIA GPUs.

### Bonsai ↔ Qwen map (read this first)

Both catalog options are **compressed Qwen3.6-27B** (Apache 2.0), not Qwen 2.5
checkpoints. AVO’s default understand ladder is still Qwen **2.5** sizes. Lead with
**VRAM capacity**, then quality:

| Catalog id | Bonsai capacity (Watch) | ≈ Full Qwen3.6-27B capacity | Quality |
| --- | --- | --- | --- |
| `bonsai-27b-gguf` | **~4 GB weights / ~8 GB VRAM** (1-bit GGUF + `mmproj`) | **≈ Qwen3.6-27B FP16 ~54 GB VRAM** (Q4 ~18 GB) | ~90% of full 27B — *not* a 7B |
| `ternary-bonsai-27b-gguf` | **~7 GB weights / ~10–12 GB VRAM** (ternary GGUF + `mmproj`) | **≈ Qwen3.6-27B FP16 ~54 GB VRAM** (same base, less compression) | ~95% of full 27B — heavier than 1-bit |

One-line operator shorthand (capacity first):

- **Bonsai 27B 1-bit ~4–8 GB VRAM (≈ Qwen3.6-27B ~54 GB FP16)**
- **Ternary Bonsai 27B ~7–12 GB VRAM (≈ Qwen3.6-27B ~54 GB FP16)**

Vs AVO’s Qwen **2.5** ladder (footprint only — different generation):

- 1-bit sits in the **`qwen2.5-7b`** VRAM band (~10 GB catalog)
- Ternary sits **between `qwen2.5-7b` and `qwen2.5-14b`**

Do **not** read “fits in ~8 GB” as “quality like 7B”. Do **not** treat Bonsai as a
rename of `qwen2.5-32b` — the base is **Qwen3.6-27B**; the ~54 GB figure is the
uncompressed FP16 capacity of that base, not AVO’s Qwen 2.5 32B catalog row.

| Catalog id | Hugging Face |
| --- | --- |
| `bonsai-27b-gguf` | [`prism-ml/Bonsai-27B-gguf`](https://huggingface.co/prism-ml/Bonsai-27B-gguf) |
| `ternary-bonsai-27b-gguf` | [`prism-ml/Ternary-Bonsai-27B-gguf`](https://huggingface.co/prism-ml/Ternary-Bonsai-27B-gguf) |

Watch vision **requires** the Bonsai `mmproj` (multimodal projector). License and
HF URLs also live on the catalog option `notes` / `hfRepo` fields.

### Pin

Set either:

- `.avo/state.json` → `models.understand` = `bonsai-27b-gguf` (or `ternary-bonsai-27b-gguf`), or
- project `avo.project.json` → `models.understand` (project wins over state)

Empty / unpinned understand still resolves to `qwen2.5-7b`. Confirm with
`python -m avo.models_cli show`.

### Operator load path (no watch-skill GGUF flag)

**watch-skill does not load GGUF or `mmproj`.** There is no `--gguf` /
`--mmproj` on the Watch CLI. Weights run in operator-owned **llama.cpp**;
watch-skill talks HTTP via `setup-vision --provider custom`.

1. **Download weights manually** from the HF repos above (language GGUF + vision
   `mmproj`). AVO does **not** auto-download in CI, Gate 1, or `npm run setup`.
2. Start **llama-server** (CUDA) with the GGUF and `--mmproj`. Prefer **4-bit KV**
   and a **modest context** sized for Watch frames + a short prompt — do not
   treat 262K context as a Watch requirement. Runtime must support Prism
   `Q1_0_g128` for the 1-bit GGUF.
3. Point watch-skill at that OpenAI-compatible server:

```bash
watch-skill setup-vision --provider custom \
  --base-url http://127.0.0.1:8080/v1 \
  --api-key none --model <server-model-name>
```

4. Export AVO preflight env (paths must exist before Watch runs with a Bonsai pin):

| Env | Purpose |
| --- | --- |
| `AVO_UNDERSTAND_GGUF` | Absolute path to the language GGUF file |
| `AVO_UNDERSTAND_MMPROJ` | Absolute path to the vision `mmproj` |
| `WATCHSKILL_CUSTOM_BASE_URL` | Custom vision base URL (e.g. `http://127.0.0.1:8080/v1`) |

AVO does not spawn `llama-server`. If Bonsai is pinned and any of the above is
missing, Watch preflight fails closed (no silent fallback to Qwen while
disclosure says Bonsai).

### Clone gap: `custom` provider

If `setup-vision` rejects `--provider custom`, the local `tools/watch-skill`
clone is too old (July 2026 clones lacked `custom`). Pull the latest
`tools/watch-skill` from upstream `main`, then re-run setup-vision.

### Concurrent Whisper + Bonsai

Do **not** claim Whisper `large-v3` and Bonsai both fit on one ~10 GB GPU.
Hardware advisory notes may warn about concurrent VRAM contention; treat that as
a real risk, not a supported dual-resident default.

## Swapping models

| Job | How to change |
| --- | --- |
| Transcribe (local) | Re-run setup with `--model medium`, or set `avo.project.json` → `transcription.model` |
| Understand / plan | Set `.avo/state.json` → `models.understand` / `models.plan`, or project `models.*` |
| Understand (optional Bonsai) | Pin `models.understand` to a Bonsai catalog id after llama-server + `setup-vision --provider custom` (see above) |
| Paid transcribe | `avo.config.json` `models.transcribe_paid`; requires `ELEVENLABS_API_KEY` |

See [`docs/adapters.md`](adapters.md) for port/adapter boundaries.
