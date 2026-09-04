# /avo.grade Command

**Timeline integration:** Owns

## Workflow guidance

**Workflow steps:** Validate grade prerequisites → Run grade → Verify and report the grade result
**Step state source:** pipeline-run.json plus the current canonical timeline revision
**Stopping conditions:** Missing required input, a failed or stale gate, a required human decision, or verified grade completion
**Valid next commands:** /avo.color or /avo.watch

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

Creative grade pass using `grade.py` presets (distinct from `/avo.color` checklist QC).

**Skill:** [`agent-skills/avo-pipeline/references/grade.md`](../../agent-skills/avo-pipeline/references/grade.md)

---

## Usage

```
/avo.grade
Provider: my-channel
The footage is at C:/Videos/my-edit
```

---

## Instructions

1. Parse `Provider` and footage location (`rawDir`).
2. Follow [`grade.md`](../../agent-skills/avo-pipeline/references/grade.md).

## Canonical track integration

Grade revisions update exact video layers and emit candidate-bound color evidence; they do not alter CMap/BMap timing.

## Shared timeline gateway

Uses shared timeline storage, transition guards, invalidation, and AI review services. It cannot maintain private CMap, BMap, sync, track, animation, or approval truth.
