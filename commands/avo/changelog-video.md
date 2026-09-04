# /avo.changelog-video Command

**Timeline integration:** Profile

## Workflow guidance

**Workflow steps:** Validate changelog video prerequisites → Run changelog video → Verify and report the changelog video result
**Step state source:** the child pipeline-run.json and its parent timeline lineage
**Stopping conditions:** Missing required input, a failed or stale gate, a required human decision, or verified changelog video completion
**Valid next commands:** /avo.watch

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

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
