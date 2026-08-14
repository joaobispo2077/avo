# /avo.end-screen Command

**Timeline integration:** Owns

YouTube end-screen safe zone and asset checklist from approved master.

**Skill:** [`agent-skills/avo-pipeline/references/end-screen.md`](../../agent-skills/avo-pipeline/references/end-screen.md)

---

## Usage

```
/avo.end-screen
Provider: my-channel
rawDir: /path/to/footage
Footage: edit/masters/20260801-review-master-v001.mp4
```

---

## Instructions

1. Require approved master export.
2. Review last ~20s for end-screen safe zones.
3. Write checklist from template to `edit/review/end-screen-checklist.md`.

## Canonical track integration

End screens are packaging video layers on the approved output timeline and must respect platform timing, faces, captions, evidence, and safe areas.

## Shared timeline gateway

Uses shared timeline storage, transition guards, invalidation, and AI review services. It cannot maintain private CMap, BMap, sync, track, animation, or approval truth.
