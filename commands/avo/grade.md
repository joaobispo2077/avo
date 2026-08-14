# /avo.grade Command

**Timeline integration:** Owns

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
