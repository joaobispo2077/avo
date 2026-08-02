# /avo.pr-video Command

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
