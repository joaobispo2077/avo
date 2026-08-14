# /avo.changelog-video Command

**Timeline integration:** Profile

Router to weekly changelog → branded video skill.

**Skill:** [`agent-skills/avo-pipeline/references/changelog-video.md`](../../agent-skills/avo-pipeline/references/changelog-video.md)

---

## Usage

```
/avo.changelog-video
Provider: my-channel
ProjectDir: /path/to/changelog-video
Source: /path/to/CHANGELOG-week.md
```

---

## Instructions

1. Parse `Provider`, `ProjectDir`, `Source` (changelog markdown path).
2. Follow [`changelog-video.md`](../../agent-skills/avo-pipeline/references/changelog-video.md).

## Shared timeline gateway

Runs the base pipeline with format-specific diagnosis and policy. It creates its own timeline context for derivatives and cannot bypass lineage, invalidation, Watch, transcript, or approval gates.
