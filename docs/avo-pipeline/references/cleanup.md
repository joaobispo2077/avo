# /avo.cleanup reference

Implements [`docs/avo-workflow.md`](../../avo-workflow.md) §7 step 2. Owning tool: rimraf (cross-platform).

## Preserved-set invariant (release-blocking)

After cleanup, **exactly** these survive:

| Artifact | Typical path |
| -------- | ------------ |
| Raw file | `<rawDir>/raw/` or declared source |
| Initial transcript | `edit/transcripts/` (first pass) |
| Final transcript | From **approved master** basename |
| Final master | `edit/masters/` or approved export |

## Delete candidates

Everything else under `<rawDir>/edit/` created by the run: previews, review packages, intermediates, scratch animations, verify frames, etc.

## Rules

- Use **rimraf**, not `rm -rf` / `del`
- Refuse if delete list intersects preserved set
- `--dry-run` lists paths only
- Final transcript MUST be generated from master export, not source footage

## Telemetry after cleanup

Report space freed + preserved-set size (pairs with `/avo.telemetry` JSON shape).
