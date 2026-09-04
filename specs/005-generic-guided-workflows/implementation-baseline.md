# Implementation Baseline

**Captured**: 2026-09-01

**Branch**: `feature/avo-mcp` — preserved; agents must not create or switch branches.

## Worktree ownership

The implementation started from a dirty user-owned worktree. Existing modified and untracked files must be patched in place and must not be reset or overwritten. The baseline included changes in Shorts schemas/runtime/tests, Watch/review/QC, audio gain, grading, rendering, project inventory, reconstruction, and technical-QC guidance, plus untracked source-fidelity and grade/fidelity tests.

The exact starting list is available in the session log from `git status --short`. Any later unrelated changes remain user-owned.

## Focused baseline

Command:

```text
rtk uv run --frozen --extra dev pytest -q tests/test_audio_gain.py tests/test_grade.py tests/test_shorts_captions.py tests/test_project_inventory.py tests/test_reconstruction_bundle.py tests/test_shorts_delivery.py tests/test_watch_adapter.py tests/test_source_fidelity_qc.py
```

Result: **70 passed in 7.92s**.

The first sandboxed attempt could not access the existing uv cache. The approved rerun used that cache and passed. This is an environment permission event, not a product failure.

## Phase 2 completion

Command:

```text
rtk uv run --frozen --extra dev pytest -q tests/test_audio_gain.py tests/test_grade.py tests/test_shorts_captions.py tests/test_project_inventory.py tests/test_reconstruction_bundle.py tests/test_shorts_delivery.py tests/test_render_duration.py
```

Result: **54 passed in 5.16s** on 2026-09-02. No project-only failure was
deferred. The cross-platform grade test proves FFmpeg writes relative metadata
inside a private scratch directory, and the dead `ffmpeg_filter_file_arg()`
helper was removed only after the repository use audit found no production
caller.

## Implementation constraints

- Preserve the reusable behavior covered by the baseline.
- Keep provider/video-specific fixtures under `tests/projects/` or external footage projects.
- Add neutral core fixtures for new generic contracts.
- Record focused story and final quality results in `verification.md`.
