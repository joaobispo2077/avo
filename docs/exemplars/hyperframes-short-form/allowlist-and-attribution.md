# Allowlist extension — short-form vertical

Extends [`../hyperframes-product-promo/allowlist-and-attribution.md`](../hyperframes-product-promo/allowlist-and-attribution.md).

## Additional allowed (short-form)

- 9:16 composition HTML (`1080×1920`)
- Face **placeholder** div in exemplar (labeled stub — swap for `<video>` at project time)
- Transcript JSON schema references in docs (no user media)
- `shift()` function examples in markdown (audio-sync protocol)

## Additional forbidden

- Talking-head `.mp4` / camera originals in `docs/exemplars/`
- Student-kit AIS caption accent hex in compositions (use provider tokens)
- Real `AnalyserNode` / live audio in render path (use seeded offline features)

## Primary upstream references

| Source | Use |
| ------ | --- |
| `.claude/skills/short-form-video/SKILL.md` | Scaffold, face-mode, verification gate |
| `video-projects/may-shorts-19` | Local reference (clone upstream) |
| `video-projects/may-shorts-18` | Iteration comparison |

Attribution: MIT compositions — [hyperframes-student-kit](https://github.com/nateherkai/hyperframes-student-kit).
