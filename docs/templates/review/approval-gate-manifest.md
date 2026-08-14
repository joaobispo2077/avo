# Approval gate — {{checkpoint}}

**Status:** pending · **Updated:** {{iso-date}}  
**Provider:** {{provider}} · **Project:** {{rawDir}}

## What to review

Open these files before approving:

| File | Why |
| --- | --- |
| `edit/preview/{{checkpoint}}.mp4` | Proof render — watch end-to-end |
| `edit/review/{{checkpoint}}/approval-gate.md` | This checklist |
| {{additional-paths}} | Agent fills per stage (EDL, transcript, stills, …) |

## watch-skill summary

- **Confidence:** {{high|low|escalated}}
- **Defects addressed this pass:** {{brief list or "none"}}

## Transcription / agent analysis

- **Transcript reviewed:** {{path}}
- **Findings:** {{names/terms fixed, caption alignment, cut notes}}

## Creator decision

- [ ] **Approve** — promote resolution / advance to next stage
- [ ] **Request changes** — {{describe}}

---

_Agent: set Status to `approved` with date when the user approves. Do not promote until a box is checked and confirmed in chat._

## Machine authority

Adjacent review.json is authoritative: exact candidate SHA-256, dependency hashes, structured revision/diff change summary, stale dependencies, evidence tool/version/time, scope, coverage, findings, fix revisions, attempts, blockers, and approval identity. This Markdown file is a generated human projection. Editing it cannot create approval or freshen stale evidence.
