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


## Code-drawn motion, when present

- Motion package: {{not prepared / immutable code-drawn-review.json path + file hash + reviewHash}}
- Exact source manifest/version, original input lock and receipt: {{actual references}}
- Engine/route, runtime/dependency and output contract: {{actual recorded identities}}
- Contact sheets, full/small sampled frames and transition strips: {{actual paths + hashes}}
- Loop seam aid and actual consecutive picture/audio playback: {{not requested / pending / actual evidence}}
- Requested / decoded / inspected coverage and gaps: {{actual separate counts and ranges}}
- Timestamped finding, fix revision and later current-candidate recheck: {{open / actual evidence}}

The package's `needs-human-judgment` state and empty approval are intentional.
Generated previews, a self-score or elapsed time cannot satisfy Watch,
transcript/listening, regression or creator approval. Any changed source,
candidate, dependency or preview requires fresh affected evidence. Delivery
metadata may reference the package only with the exact final master profile
and native materialization dependency lock.
