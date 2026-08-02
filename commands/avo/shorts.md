# /avo.shorts Command

Orchestrated YouTube Shorts workflow (9:16, duration checks, captions, deliver). **Not** the same as `/avo.guidelines --shorts` (diagnosis only).

**Skill:** [`agent-skills/avo-pipeline/references/shorts.md`](../../agent-skills/avo-pipeline/references/shorts.md)

---

## Usage

```
/avo.shorts
Provider: my-channel
rawDir: /path/to/footage
identity: anchor
```

Optional: `--from-master` · `--max-duration 60` · `--skip-motion` · `--preview`

---

## Role

Phase 0 Shorts diagnosis → trim → watch-skill LOOP → optional motion → captions → duration check → deliver. Delegates to stage references; preserves human approval gates.

---

## Instructions

1. Parse `Provider`, `rawDir` (required).
2. Run phase 0 from [`guidelines-shorts.md`](../../agent-skills/avo-pipeline/references/guidelines-shorts.md).
3. If `--from-master`, delegate to [`reframe.md`](../../agent-skills/avo-pipeline/references/reframe.md) before captions/deliver.
4. Warn and block promotion when duration exceeds `--max-duration` (default 60) without EDITLOG override.

---

## Example

```text
/avo.shorts
Provider: my-channel
The footage is at C:/Videos/short-001
identity: anchor
```
