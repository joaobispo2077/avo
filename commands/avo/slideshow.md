# /avo.slideshow Command

**Timeline integration:** Profile

## Workflow guidance

**Workflow steps:** Validate slideshow prerequisites → Run slideshow → Verify and report the slideshow result
**Step state source:** the child pipeline-run.json and its parent timeline lineage
**Stopping conditions:** Missing required input, a failed or stale gate, a required human decision, or verified slideshow completion
**Valid next commands:** /avo.watch

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

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
