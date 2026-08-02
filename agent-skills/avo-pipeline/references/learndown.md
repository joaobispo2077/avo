# /avo.learndown reference

Implements [`docs/avo-workflow.md`](../../docs/avo-workflow.md) §7 step 1.

## Preconditions

- Human approved **final master**
- `Provider` declared
- Session started at pipeline kickoff (`session.py start` → `pre.json`)
- ai-memory installed (`--with-memory` setup) or command notes skip in wrap

## Actions (REQUIRED)

1. **Inventory report:** `python -m avo.project_inventory report --raw-dir <rawDir> --master-basename <stem> [--pre .avo/sessions/<id>/pre.json] [--scratch-out] [--session-id <id>]`
2. **Draft wrap:** agent narrative + `python -m avo.wrap draft …` → `<rawDir>/avo.wrap.draft.md/json` (`status: "draft"`). Auto-exports `providers/<slug>/learndowns/<entry-id>/` unless `--no-export`.
3. Consolidate session learnings scoped to **provider** (not global bleed) when ai-memory present
4. **Learndown telemetry:** `Telemetry.learndown()` — space used vs freed preview, preserved-set size
5. Never store secrets in memory or wrap JSON

## Provider export (filesystem)

Each draft/final wrap updates:

- `providers/<slug>/learndowns/<YYYYMMDD-topic>/learndown.json`
- `providers/<slug>/learndowns/<YYYYMMDD-topic>/learndown.md`
- Wrap copies (`wrap.draft.*`, and `wrap.*` when final)
- Catalog: `providers/<slug>/learndowns/index.json`

Backfill from an existing wrap: `python -m avo.learndown_export backfill --wrap-json <path>` (resolves provider from `avo.project.json` when wrap JSON says `unknown`).

## Scratch inventory (optional)

Use `--scratch-out --session-id <id>` on inventory `report` to stage the full JSON under `.avo/tmp/learndown/<session-id>/`. Never write scratch JSON at repo root. Cleanup with `--session-id` purges the scratch dir after successful delete.

## Draft wrap contents

- Provider, title (if known), master basename, editorial summary
- Space estimates (pre-cleanup footprint, delete candidates, preserved)
- Table of files **scheduled for deletion**; list of **preserved artifacts**
- ai-memory note (filed / skipped)

## Pair with cleanup

Learndown does **not** delete files. Run `/avo.cleanup` after learndown completes.

## If ai-memory absent

Print one-line skip notice in wrap learning section; proceed to cleanup when user ready.
