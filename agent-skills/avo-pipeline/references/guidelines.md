# /avo.guidelines reference

Load **one** flag per invocation. Guidelines commands diagnose; they do not run ffmpeg or cut.

## Router

| Flag | Read |
| ---- | ---- |
| `--youtube` | [`guidelines-youtube.md`](guidelines-youtube.md) |
| `--eq` | [`guidelines-eq.md`](guidelines-eq.md) |
| `--tiktok` | [`guidelines-tiktok.md`](guidelines-tiktok.md) |
| `--shorts` | [`guidelines-shorts.md`](guidelines-shorts.md) |

## Workflow

1. Parse flag (required).
2. Load slice + [`AGENTS.md`](../../../AGENTS.md) core rules.
3. Output **format diagnosis** before any edit proposal.
4. If repo skills installed, also load matching skill (`youtube-format-selection`, `audio-post-production`, …).

## Output shape

```text
Format diagnosis
- Primary format:
- Viewer promise:
- Pacing density:
- Risks:

Checklist (approve before /avo.pipeline or /avo.trim)
- [ ] ...
```
