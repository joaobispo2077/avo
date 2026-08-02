# /avo.learndown reference

Implements [`docs/avo-workflow.md`](../../docs/avo-workflow.md) §7 step 1.

## Preconditions

- Human approved **final master**
- `Provider` declared
- Session started at pipeline kickoff (`session.py start` → `pre.json`)
- ai-memory installed (`--with-memory` setup) or command notes skip in wrap

## Actions (REQUIRED)

1. **Inventory report:** `python -m avo.project_inventory report --raw-dir <rawDir> --master-basename <stem> [--pre .avo/sessions/<id>/pre.json]`
2. **Draft wrap:** agent narrative + `python -m avo.wrap draft …` → `<rawDir>/avo.wrap.draft.md/json` (`status: "draft"`)
3. Consolidate session learnings scoped to **provider** (not global bleed) when ai-memory present
4. **Learndown telemetry:** `Telemetry.learndown()` — space used vs freed preview, preserved-set size
5. Never store secrets in memory or wrap JSON

## Draft wrap contents

- Provider, title (if known), master basename, editorial summary
- Space estimates (pre-cleanup footprint, delete candidates, preserved)
- Table of files **scheduled for deletion**; list of **preserved artifacts**
- ai-memory note (filed / skipped)

## Pair with cleanup

Learndown does **not** delete files. Run `/avo.cleanup` after learndown completes.

## If ai-memory absent

Print one-line skip notice in wrap learning section; proceed to cleanup when user ready.
