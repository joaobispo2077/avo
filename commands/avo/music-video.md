# /avo.music-video Command

**Timeline integration:** Profile

Router to music track → visual video skill.

**Skill:** [`agent-skills/avo-pipeline/references/music-video.md`](../../agent-skills/avo-pipeline/references/music-video.md)

---

## Usage

```
/avo.music-video
Provider: my-channel
ProjectDir: /path/to/music-video
Source: /path/to/track.mp3
```

---

## Instructions

1. Parse `Provider`, `ProjectDir`, `Source` (audio file or video-with-audio path).
2. Follow [`music-video.md`](../../agent-skills/avo-pipeline/references/music-video.md).

## Shared timeline gateway

Runs the base pipeline with format-specific diagnosis and policy. It creates its own timeline context for derivatives and cannot bypass lineage, invalidation, Watch, transcript, or approval gates.
