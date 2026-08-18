# /avo.cleanup reference

Implements [`docs/avo-workflow.md`](../../docs/avo-workflow.md) §7 step 2. Owning tools: `python -m avo.cli cleanup`, `wrap.py`, `stats.py`, rimraf (cross-platform).

## Scratch roots

Orchestrator scratch lives under `.avo/tmp/<kind>/<session-id>/` with kinds
`learndown`, `qc`, `shorts-proof`, `session` (use `avo.scratch.scratch_path` /
`avo.avo_state.tmp_dir`). Footage preview, verify, and review proofs live under
`<rawDir>/edit/` on the footage volume — they are not orchestrator-repo files.

Repo-root `.tmp-*` is a defect. Never write QC or proofs into the AVO clone
(repo root, `specs/`, `src/`). A writer that cannot use those roots must fail
closed with remediation pointing at `avo.scratch` / `avo.avo_state.tmp_dir`.
Existing repo-root tmp (`.tmp-*`, `.codex-qc/`, `.codex-tmp/`,
`.avo-test-sessions/`, `NUL`, `err.txt`, `out.txt`, `*.orig`) is listed for
delete, never committed, and removed only after explicit user confirm.

## Preserved-set invariant (release-blocking)

Cleanup is allowed on **canonical** projects only after `edit/timeline/reconstruction-bundle.json` verifies. **Legacy** projects (the five indexes absent) are cleaned after execute copies reconstruction sources into preserved locations — do not run migrate-timeline for that copy.

| Artifact | Typical path |
| -------- | ------------ |
| Raw file | `<rawDir>/raw/` or declared source |
| Initial transcript | `edit/transcripts/` (first pass) |
| Final transcript | From **approved master** basename |
| Final master | `edit/masters/` or approved export |
| Canonical timeline | indexes, immutable revisions/events, projection lineage |
| Review audit | candidate-bound review JSON and exact approval events |
| Reconstruction bundle | graph of every preserved file and SHA-256 |
| Footage-root EDITLOG | `<rawDir>/EDITLOG.md` — living AVO digest + Human notes (not a delete candidate when indexes exist) |

## Workflow (REQUIRED steps)

1. **Build bundle:** `python -m avo.cli cleanup bundle --project <avo.project.json> --master-basename <stem> --actor <id>` (canonical indexes only; not migrate-timeline)
2. **Verify:** `python -m avo.cli cleanup verify --project <avo.project.json> --master-basename <stem>` — compact `verifyErrors`
3. **Dry-run:** `python -m avo.cli cleanup dry-run --project <avo.project.json> --master-basename <stem> [--session-id <id> --scratch-out]` — compact JSON; writes nothing; `--full-paths` debug-only
4. **Execute:** `python -m avo.cli cleanup execute --project <avo.project.json> --master-basename <stem> [--session-id <id>]` — not a dry-run. Prints compact JSON **before** session tmp purge. Verify → assert no preserved ∩ delete → `npx rimraf` footage delete candidates under `<rawDir>/edit/`. On success with `--session-id`, purge **all** `.avo/tmp/<kind>/<session-id>/` kinds. Incomplete preserved set or preserved ∩ delete refuses the run and skips purge. **Do not** write `.avo/tmp/**/execute_*.py` walk/delete scripts.
5. **Final wrap:** `python -m avo.wrap final …` → `<rawDir>/avo.wrap.md/json` (`status: "final"`). Keep `avo.wrap.draft.*`. Updates provider learndown entry + index.
6. **Record session:** `python -m avo.stats record --wrap-json <rawDir>/avo.wrap.json`

## Delete candidates

Only files absent from the verified reconstruction graph: bulky superseded proof
media under `<rawDir>/edit/`, intermediates, scratch animation renders, and
verify frames. Review JSON, approvals, canonical ancestors, and their hashes are
never delete candidates. Orchestrator-session scratch is purged separately via
`--session-id` as above — not by treating footage `edit/` proofs as files inside
the AVO clone.

## Rules

- Use **rimraf**, not `rm -rf` / `del`, for footage delete candidates
- Refuse if delete list intersects preserved set (release-blocking)
- `cleanup dry-run` returns compact JSON (counts/sample); `cleanup execute` is the destructive step
- `--full-paths` is CLI debug only; MCP cleanup tools stay compact
- Use the built-in inventory/wrap/cleanup CLIs. Ad-hoc `.avo/tmp/**/execute_*.py` walkers are out of contract
- Windows `--project` maps WSL `rawDir` `/mnt/<letter>/...` to `<letter>:\...`
- OSError on walk/unlink skips that path and increments leftover counts; it does not abort
- Legacy projects (no five canonical indexes): execute copies EDL/logs into preserved locations; dry-run does not write
- Final transcript MUST be generated from master export, not source footage
- Never write QC/proofs as repo-root `.tmp-*`

## Final wrap additions (vs draft)

- Actual freed bytes, preserved bytes, deleted file count
- File sections: added then removed, produced/preserved, deleted on cleanup
- Link to footage-root `EDITLOG.md` when present (hybrid digest + Human notes; do not hand-edit the marked digest)
- Re-export the provider learndown entry; do not overwrite an existing `EDITLOG.md` lock copied at draft/backfill

## Telemetry after cleanup

Report space freed + preserved-set size. Optional `Telemetry.cleanup()` when helper ships.

## Stats

Session record enables `/avo.stats` aggregate view. Privacy: [`SECURITY.md#privacy--telemetry`](../../../SECURITY.md#privacy--telemetry).
