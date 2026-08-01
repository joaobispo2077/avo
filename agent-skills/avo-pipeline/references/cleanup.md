# /avo.cleanup reference

Implements [`docs/avo-workflow.md`](../../docs/avo-workflow.md) §7 step 2. Owning tools: `project_inventory.py`, `wrap.py`, `stats.py`, rimraf (cross-platform).

## Preserved-set invariant (release-blocking)

After cleanup, **exactly** these survive:

| Artifact | Typical path |
| -------- | ------------ |
| Raw file | `<rawDir>/raw/` or declared source |
| Initial transcript | `edit/transcripts/` (first pass) |
| Final transcript | From **approved master** basename |
| Final master | `edit/masters/` or approved export |

## Workflow (REQUIRED steps)

1. **Verify:** `python helpers/project_inventory.py verify --raw-dir <rawDir> --master-basename <stem>`
2. **Dry-run (recommended):** `… cleanup --dry-run` — list paths only
3. **Execute:** `… cleanup` — verify → assert no preserved ∩ delete → `npx rimraf`
4. **Final wrap:** `python helpers/wrap.py final …` → `<rawDir>/avo.wrap.md/json` (`status: "final"`). Keep `avo.wrap.draft.*`.
5. **Record session:** `python helpers/stats.py record --wrap-json <rawDir>/avo.wrap.json`

## Delete candidates

Everything else under `<rawDir>/edit/` created by the run: previews, review packages, intermediates, scratch animations, verify frames, etc.

## Rules

- Use **rimraf**, not `rm -rf` / `del`
- Refuse if delete list intersects preserved set (release-blocking)
- `--dry-run` lists paths only
- Final transcript MUST be generated from master export, not source footage

## Final wrap additions (vs draft)

- Actual freed bytes, preserved bytes, deleted file count
- File sections: added then removed, produced/preserved, deleted on cleanup
- Link to `EDITLOG.md` when present

## Telemetry after cleanup

Report space freed + preserved-set size. Optional `Telemetry.cleanup()` when helper ships.

## Stats

Session record enables `/avo.stats` aggregate view. Privacy: [`SECURITY.md#privacy--telemetry`](../../../SECURITY.md#privacy--telemetry).
