# BL-015 — Concurrent workstreams

**Status:** Shipped (registry v1 + work modes v2)  
**Slash surface:** _(docs + `avo.videos` CLI + stats filter)_

## Summary

Parallel videos per provider via external `rawDir` + in-repo registry stubs. **Parallelism** (one chat per video, recommended) and **concurrency** (same chat, declare active video) work modes. Per-video runtime state in `.avo/state.json`. Advisory locks under `<rawDir>/edit/.avo-lock.json`.

## Spec

[`specs/active/provider-videos-config/spec.md`](../active/provider-videos-config/spec.md)

## CLI

- `python -m avo.init_project --video-id <slug> --raw-dir <path> --provider <slug>`
- `python -m avo.videos list|show|resolve|reindex`
- `python -m avo.videos context set|show|clear`
- `python -m avo.videos lock acquire|release|status`
- `python -m avo.stats show --provider <slug> [--video-id <id>|--raw-dir <path>]`

## Docs

- [docs/video-work-modes.md](../../docs/video-work-modes.md)
