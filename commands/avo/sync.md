# /avo.sync Command

**Timeline integration:** Owns

## Workflow guidance

**Workflow steps:** Validate sync prerequisites → Run sync → Verify and report the sync result
**Step state source:** pipeline-run.json plus the current canonical timeline revision
**Stopping conditions:** Missing required input, a failed or stale gate, a required human decision, or verified sync completion
**Valid next commands:** /avo.transcribe or /avo.trim

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

Audio sync diagnosis before creative cutting (external recorder, multicam, drift).

**Skill:** [`agent-skills/avo-pipeline/references/sync.md`](../../agent-skills/avo-pipeline/references/sync.md)

---

## Usage

```
/avo.sync
Provider: my-channel
rawDir: /path/to/footage
```

Optional: list external audio paths in project notes

---

## Instructions

1. Inventory audio sources per AGENTS.md audio-first policy.
2. Verify sync at start, middle, end of program.
3. Write `edit/review/sync-check.md` before `/avo.trim` on long/external programs.

## Generic sync-map contract

`/avo.sync` guides picture/audio source fingerprints, streams/channels,
reference clock, calibration anchors, offset direction, drift samples,
transform selection, tolerance, and full-program residual QC. It writes
immutable `edit/timeline/sync-map.json` revisions. Constant offset, linear
drift, and piecewise transforms are supported. Positive audio delay means audio
is moved later on the picture clock. Approval blocks without full-program PASS
evidence. Correction is
materialized once from raw while generating a CMap cut; corrected deliveries
never become new sync bases.

## Shared timeline gateway

Uses shared timeline storage, transition guards, invalidation, and AI review services. It cannot maintain private CMap, BMap, sync, track, animation, or approval truth.
