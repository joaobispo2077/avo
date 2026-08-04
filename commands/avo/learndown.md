# /avo.learndown Command

Post-master provider-scoped learning consolidation and **draft wrap** preview. **ai-memory is optional** — without it, only MCP wiki consolidation is skipped; all other steps below remain **REQUIRED**.

**Skill:** [`agent-skills/avo-pipeline/references/learndown.md`](../../agent-skills/avo-pipeline/references/learndown.md) · **Optional tools:** [`docs/ai-memory-and-ai-jail.md`](../../docs/ai-memory-and-ai-jail.md)

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
2. **Inventory report (REQUIRED):** `python -m avo.project_inventory report --raw-dir <rawDir> --master-basename <stem> [--pre .avo/sessions/<id>/pre.json] [--scratch-out] [--session-id <id>]` — full JSON to stdout; with `--scratch-out`, also writes under `.avo/tmp/learndown/<session-id>/` (never repo root).
3. **Draft wrap (REQUIRED):** agent writes narrative summary; run `python -m avo.wrap draft --raw-dir <rawDir> --master-basename <stem> --summary-file <path> [--learning-note TEXT]` → `<rawDir>/avo.wrap.draft.md` + `avo.wrap.draft.json` (outside `edit/`). Wrap auto-exports a provider entry under `providers/<slug>/learndowns/<entry-id>/` (`learndown.json`, `learndown.md`, wrap copies, `index.json`). Use `--no-export` to skip.
4. **Optional — ai-memory only:** If ai-memory MCP is available, consolidate session learnings scoped to `Provider` (not global). If absent, set wrap `aiMemory: "skipped"` and note in the learning section — **do not skip steps 2, 3, 5, or 6**.
5. **Learndown telemetry (REQUIRED):** call `Telemetry.learndown()` with measured bytes (space used vs freed preview, preserved-set size).
6. **Do not** delete files; user runs `/avo.cleanup` next.

---

## Example

```text
/avo.learndown
Provider: auto-lot
rawDir: H:/footage/dealer-walk
```
