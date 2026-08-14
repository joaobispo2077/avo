# /avo.color Command

**Timeline integration:** Owns

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
