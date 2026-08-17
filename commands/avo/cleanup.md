# /avo.cleanup Command

**Timeline integration:** Admin

Delete run scratch files after a verified reconstruction bundle; preserve the
reconstruction graph; write **final wrap** and record session stats.

**Skill:** [`agent-skills/avo-pipeline/references/cleanup.md`](../../agent-skills/avo-pipeline/references/cleanup.md)

---

## Usage

```
/avo.cleanup
Provider: my-channel
rawDir: /path/to/footage
```

Optional: run `python -m avo.cli cleanup dry-run --project <avo.project.json> --master-basename <stem> [--session-id <id> --scratch-out]` first. Stdout is compact counts/sample JSON; `--full-paths` is debug-only.

Prerequisite: **final master approved**; run `/avo.learndown` first when ai-memory is installed.

---

## Role

Workflow §7 step 2. Cross-platform `rimraf` deletes footage intermediates.
**Release-blocking:** the verified reconstruction graph must survive. Records
session for `/avo.stats`.

Orchestrator scratch lives under `.avo/tmp/<kind>/<session-id>/` (`learndown`,
`qc`, `shorts-proof`, `session`). Footage proofs live under `<rawDir>/edit/` —
they are not orchestrator-repo files. Repo-root `.tmp-*` is a defect; never write
QC or proofs into the AVO clone. A writer that cannot use those roots must fail
closed with remediation pointing at `avo.scratch` / `avo.avo_state.tmp_dir`.
Existing repo-root tmp (`.tmp-*`, `.codex-qc/`, `.codex-tmp/`,
`.avo-test-sessions/`, `NUL`, `err.txt`, `out.txt`, `*.orig`) stays listed, is
never committed, and is deleted only after explicit user confirm.

---

## Instructions

1. **Build bundle (REQUIRED when canonical timeline indexes exist):** `python -m avo.cli cleanup bundle --project <avo.project.json> --master-basename <stem> --actor <id>`. Legacy projects without the five indexes skip migrate-timeline; the CLI copies `edit/edl.json` / edit logs into `edit/review/legacy-reconstruction/` and root `EDITLOG.md` / `AUDIO-EDITLOG.md` on execute only.
2. **Verify preserved set (REQUIRED):** `python -m avo.cli cleanup verify --project <avo.project.json> --master-basename <stem>` — compact JSON with `verifyErrors`; refuse if any preserved artifact is missing.
3. **Dry-run (recommended):** `python -m avo.cli cleanup dry-run --project <avo.project.json> --master-basename <stem> [--session-id <id> --scratch-out]` — compact JSON (`candidateCount`, `candidateSample`, leftover OSError skips). Writes nothing (no legacy copies). `--full-paths` is debug-only. Full lists belong in scratch, not in tmp walk/delete scripts.
4. **Execute cleanup (REQUIRED):** `python -m avo.cli cleanup execute --project <avo.project.json> --master-basename <stem> [--session-id <id>]` — not a dry-run. Prints compact JSON **before** purging `.avo/tmp/<kind>/<session-id>/`. Verify → assert no preserved paths in delete list → `npx rimraf` footage delete candidates under `<rawDir>/edit/`. On success with `--session-id`, purge **all** session kinds. Incomplete preserved set or intersection **aborts** (`status: blocked`, `verifyErrors`) and skips purge. **Do not** invent `.avo/tmp/**/execute_*.py` walkers.
5. **Final wrap (REQUIRED):** agent summary (`--summary-file` remains agent-authored) + `python -m avo.wrap final --raw-dir <rawDir> --master-basename <stem> --summary-file <path> [--session-id ID]` → `<rawDir>/avo.wrap.md` + `avo.wrap.json` with `status: "final"`, sample-capped file lists, and `deletedCount`. Retain `avo.wrap.draft.*`. Updates the provider learndown entry and `index.json`.
6. **Record session (REQUIRED):** `python -m avo.stats record --wrap-json <rawDir>/avo.wrap.json` — append to `.avo/state.json` → `stats.sessions[]`, update `stats.totals`.
7. Emit cleanup telemetry (optional `Telemetry.cleanup()` when available): bytes freed + preserved-set size.

---

## Preserved set

Cleanup is allowed only after a verified reconstruction graph exists:

- **Canonical projects** (all five indexes `cmap`, `bmap`, `tracks`, `animation`, `sync-map`): `edit/timeline/reconstruction-bundle.json` must verify.
- **Legacy projects** (indexes absent): execute copies EDL/edit logs into preserved locations; `cleanup bundle` / migrate-timeline is not required.
- Raw source file(s) in `rawDir`
- Initial transcript artifact
- Final transcript from **approved master** (`edit/transcripts/<master-basename>.*`)
- Final master output
- Canonical timeline indexes, immutable revisions/events, projection lineage (when present)
- Candidate-bound review evidence and exact approvals
- The reconstruction bundle itself (canonical projects)

`--project` on Windows maps WSL `rawDir` values `/mnt/<letter>/...` to `<letter>:\...`. Do not author tmp delete scripts around a missing path.

---

## Example

```text
python -m avo.cli cleanup dry-run --project /videos/review/avo.project.json --master-basename 20260814-review-master-v001
```

## Shared timeline gateway

Resolves provider/video context but performs no editorial timeline mutation. Reports and configuration reference canonical artifact/revision identities.
