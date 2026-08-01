# /avo.learndown Command

Post-master provider-scoped learning consolidation (ai-memory).

**Skill:** [`docs/avo-pipeline/references/learndown.md`](../../docs/avo-pipeline/references/learndown.md)

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

Workflow §7 step 1. Consolidate iteration learnings under the provider. No-op if ai-memory not installed.

---

## Instructions

1. Confirm master exists in `edit/masters/` or approved final export path.
2. If ai-memory available: run learndown scoped to `Provider`; file decisions under provider, not global.
3. Report space used vs space freed (preview before cleanup).
4. **Do not** delete files; user runs `/avo.cleanup` next (or pipeline cleanup step).

---

## Example

```text
/avo.learndown
Provider: auto-lot
rawDir: H:/footage/dealer-walk
```
