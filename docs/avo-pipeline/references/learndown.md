# /avo.learndown reference

Implements [`docs/avo-workflow.md`](../../avo-workflow.md) §7 step 1.

## Preconditions

- Human approved **final master**
- `Provider` declared
- ai-memory installed (`--with-memory` setup) or command no-ops with notice

## Actions

1. Consolidate session learnings scoped to **provider** (not global bleed)
2. File routing preferences, caption identity wins, cut patterns that worked
3. Report **space used** across iterations (preview for cleanup)
4. Never store secrets in memory

## Pair with cleanup

Learndown does **not** delete files. Run `/avo.cleanup` after learndown completes.

## If ai-memory absent

Print one-line skip notice; proceed to cleanup when user ready.
