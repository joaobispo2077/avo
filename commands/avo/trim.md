# /avo.trim Command

**Timeline integration:** Owns

## Workflow guidance

**Workflow steps:** Validate trim prerequisites → Run trim → Verify and report the trim result
**Step state source:** pipeline-run.json plus the current canonical timeline revision
**Stopping conditions:** Missing required input, a failed or stale gate, a required human decision, or verified trim completion
**Valid next commands:** /avo.watch

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

Transcribe and cut only. Skip motion unless the user asks to continue.

**Skill:** [`agent-skills/avo-pipeline/references/trim.md`](../../agent-skills/avo-pipeline/references/trim.md)

---

## Usage

```
/avo.trim
Provider: my-channel
rawDir: /path/to/footage
Footage: /path/to/main.mp4
```

Optional: `from: 9:30` `to: 12:00` (limit working region) · `--preview`

---

## Role

Run stages 1–2 (+ deliver cut master): transcribe → edit/caption → watch-skill LOOP → human approval → export edit master. No HyperFrames pass by default.

---

## Instructions

1. Parse `Provider`, `rawDir`, `Footage` (required).
2. Follow [`SKILL.md`](../../SKILL.md) process through edit proof.
3. Default to **360p preview** until user approves promotion.
4. After approval, render cut master to `edit/masters/` or `edit/final.mp4` per project convention.
5. Do **not** spawn motion sub-agents unless user explicitly requests `/avo.motion` next.

---

## Example

```text
/avo.trim
Provider: my-channel
rawDir: /videos/product-review
Footage: /videos/product-review/raw/take-a.mp4
```

## Canonical timeline contract

`/avo.trim` owns only CMap decisions. It inventories and fingerprints brute/raw
sources, creates an immutable `edit/timeline/cmap.json` revision in raw-source
time, generates `edit/edl.json` as a compatibility projection, renders a cut
proof, transcribes that exact proof, and runs the shared Watch/review gate.
Approval binds the CMap revision hash, cut-output SHA-256, and candidate SHA-256.
It never uses a proxy, synchronized export, previous trim, or proof as editorial
truth. Motion, music, SFX, captions, and other BMap work are out of scope.

## Shared timeline gateway

Uses shared timeline storage, transition guards, invalidation, and AI review services. It cannot maintain private CMap, BMap, sync, track, animation, or approval truth.
