# /avo.music-video Command

**Timeline integration:** Profile

## Workflow guidance

**Workflow steps:** Validate music video prerequisites → Run music video → Verify and report the music video result
**Step state source:** the child pipeline-run.json and its parent timeline lineage
**Stopping conditions:** Missing required input, a failed or stale gate, a required human decision, or verified music video completion
**Valid next commands:** /avo.watch

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

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
