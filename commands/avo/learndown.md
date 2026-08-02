# /avo.learndown Command

Post-master provider-scoped learning consolidation (ai-memory) and **draft wrap** preview.

**Skill:** [`agent-skills/avo-pipeline/references/learndown.md`](../../agent-skills/avo-pipeline/references/learndown.md)

---

## Usage

```
/avo.learndown
Provider: my-channel
rawDir: /path/to/footage
```

Prerequisite: **final master approved** by human.

---

## Role

Workflow §7 step 1. Consolidate iteration learnings under the provider. Produce pre-cleanup wrap preview. **No file deletes** — user runs `/avo.cleanup` next.

---

## Instructions

1. Confirm master exists in `edit/masters/` or approved final export path.
2. **Inventory preview (REQUIRED):** `python -m avo.project_inventory report --raw-dir <rawDir> --master-basename <stem> [--pre .avo/sessions/<id>/pre.json] [--json]`
3. **Draft wrap (REQUIRED):** agent writes narrative summary; run `python -m avo.wrap draft --raw-dir <rawDir> --master-basename <stem> --summary-file <path> [--learning-note TEXT]` → `<rawDir>/avo.wrap.draft.md` + `avo.wrap.draft.json` (outside `edit/`).
4. If ai-memory available: run learndown scoped to `Provider`; file decisions under provider, not global. If absent, note "ai-memory skipped" in wrap learning section.
5. **Learndown telemetry (REQUIRED):** call `Telemetry.learndown()` with measured bytes (space used vs freed preview, preserved-set size).
6. **Do not** delete files; user runs `/avo.cleanup` next.

---

## Example

```text
/avo.learndown
Provider: auto-lot
rawDir: H:/footage/dealer-walk
```
