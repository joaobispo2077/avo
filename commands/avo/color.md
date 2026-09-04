# /avo.color Command

**Timeline integration:** Owns

## Workflow guidance

**Workflow steps:** Validate color prerequisites → Run color → Verify and report the color result
**Step state source:** pipeline-run.json plus the current canonical timeline revision
**Stopping conditions:** Missing required input, a failed or stale gate, a required human decision, or verified color completion
**Valid next commands:** /avo.deliver

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

Color and evidence integrity QC (checklist v1 — no automated grade engine).

**Skill:** [`agent-skills/avo-pipeline/references/color.md`](../../agent-skills/avo-pipeline/references/color.md)

---

## Usage

```
/avo.color
Provider: my-channel
rawDir: /path/to/footage
```

---

## Instructions

1. Run on approved master or color-locked export.
2. Checklist-only PASS/FAIL — document blockers in `edit/review/color-qc.md`.

## Canonical track integration

Grade intent belongs to an exact video layer; evidence binds the resulting candidate hash and stales on rerender.

## Shared timeline gateway

Uses shared timeline storage, transition guards, invalidation, and AI review services. It cannot maintain private CMap, BMap, sync, track, animation, or approval truth.
