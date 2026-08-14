# /avo.slideshow Command

**Timeline integration:** Profile

Router to HyperFrames slideshow skill.

**Skill:** [`agent-skills/avo-pipeline/references/slideshow.md`](../../agent-skills/avo-pipeline/references/slideshow.md)

---

## Usage

```
/avo.slideshow
Provider: my-channel
ProjectDir: /path/to/slideshow
Source: /path/to/outline.md
```

---

## Instructions

1. Parse `Provider`, `ProjectDir`, `Source` (slide outline or deck notes).
2. Follow [`slideshow.md`](../../agent-skills/avo-pipeline/references/slideshow.md).

## Shared timeline gateway

Runs the base pipeline with format-specific diagnosis and policy. It creates its own timeline context for derivatives and cannot bypass lineage, invalidation, Watch, transcript, or approval gates.
