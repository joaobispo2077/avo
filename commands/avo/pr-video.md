# /avo.pr-video Command

**Timeline integration:** Profile

## Workflow guidance

**Workflow steps:** Validate pr video prerequisites → Run pr video → Verify and report the pr video result
**Step state source:** the child pipeline-run.json and its parent timeline lineage
**Stopping conditions:** Missing required input, a failed or stale gate, a required human decision, or verified pr video completion
**Valid next commands:** /avo.watch

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

Router to the PR → video content skill. Link-only — do not duplicate skill body.

**Skill:** [`agent-skills/avo-pipeline/references/pr-video.md`](../../agent-skills/avo-pipeline/references/pr-video.md)

---

## Usage

```
/avo.pr-video
Provider: my-channel
ProjectDir: /path/to/hyperframes-project
Source: https://github.com/owner/repo/pull/123
```

---

## Role

Load `.agents/skills/pr-to-video/SKILL.md` via pipeline reference. Non-footage workflow — `ProjectDir` maps to `rawDir`.

---

## Instructions

1. Parse `Provider`, `ProjectDir`, `Source` (PR URL or owner/repo#N).
2. Follow [`pr-video.md`](../../agent-skills/avo-pipeline/references/pr-video.md).
3. Warn on private repos — token/auth required for `gh`.

## Shared timeline gateway

Runs the base pipeline with format-specific diagnosis and policy. It creates its own timeline context for derivatives and cannot bypass lineage, invalidation, Watch, transcript, or approval gates.
