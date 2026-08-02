# Port / adapter layer

AVO routes **jobs** from [`avo.config.json`](../config/avo.config.json) through a thin
**port/adapter** layer in `src/avo/adapters/`. Adapters talk to engines and external tools
via **subprocess or CLI only** — never deep-import from `tools/*` into orchestrator logic.

## Run a job

```bash
python -m avo.adapters.run_job transcribe --label local -- /path/to/video.mp4
python -m avo.adapters.run_job transcribe --label paid -- /path/to/video.mp4
```

Exit codes: `0` success, `1` adapter failure, `2` config/user error.

## Job registry

| Job | Label | Routing token | Adapter | Status |
| --- | --- | --- | --- | --- |
| transcribe | local | `video-use+faster-whisper` | `FasterWhisperAdapter` | Wired |
| transcribe | paid | `elevenlabs` | `ElevenLabsAdapter` | Stub |
| understand | local | `watch-skill` | `WatchSkillStubAdapter` | Stub |
| motion | local | `hyperframes` | `HyperframesStubAdapter` | Stub |
| motion | local | `remotion` | `RemotionStubAdapter` | Stub |
| memory | local | `ai-memory` | `AiMemoryStubAdapter` | Stub |
| plan | local | `speckit` | `SpeckitStubAdapter` | Stub |

## Adding an adapter

1. Implement `JobAdapter` with a `routing_id` and `run(request) -> JobResult`.
2. Register in `src/avo/adapters/registry.py`.
3. Add tests under `tests/test_adapters_*.py`.
4. Prefer subprocess to bundled scripts or external CLIs.

## Model metadata

Adapters populate `JobResult.models_used` (e.g. `{"transcribe": "faster-whisper:small"}`).
Phase telemetry merges resolver output into JSON `activeModels`. See
[`docs/model-transparency.md`](model-transparency.md).

## Upstream engine diffs

Before large engine edits, read
[`specs/upstream-diffs/video-use/LATEST.json`](../specs/upstream-diffs/video-use/LATEST.json)
and the linked `summary.md`. See
[`specs/upstream-diffs/video-use/README.md`](../specs/upstream-diffs/video-use/README.md).
