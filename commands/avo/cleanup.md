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

Optional: run `python -m avo.cli cleanup dry-run --project <avo.project.json> --master-basename <stem>` first (list deletes only; writes nothing).

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

1. **Build bundle (REQUIRED):** `python -m avo.cli cleanup bundle --project <avo.project.json> --master-basename <stem> --actor <id>`
2. **Verify preserved set (REQUIRED):** `python -m avo.cli cleanup verify --project <avo.project.json> --master-basename <stem>` — refuse if any preserved artifact is missing.
3. **Dry-run (recommended):** `python -m avo.cli cleanup dry-run --project <avo.project.json> --master-basename <stem>` — list delete candidates only; writes nothing.
4. **Execute cleanup (REQUIRED):** `python -m avo.cli cleanup execute --project <avo.project.json> --master-basename <stem> [--session-id <id>]` — not a dry-run. Verify → assert no preserved paths in delete list → `npx rimraf` footage delete candidates under `<rawDir>/edit/`. On success with `--session-id`, purge **all** `.avo/tmp/<kind>/<session-id>/` kinds (`learndown`, `qc`, `shorts-proof`, `session`), not only learndown. Incomplete preserved set or intersection **aborts** and skips purge.
5. **Final wrap (REQUIRED):** agent summary + `python -m avo.wrap final --raw-dir <rawDir> --master-basename <stem> --summary-file <path> [--session-id ID]` → `<rawDir>/avo.wrap.md` + `avo.wrap.json` with `status: "final"`. Retain `avo.wrap.draft.*`. Updates the provider learndown entry and `index.json`.
6. **Record session (REQUIRED):** `python -m avo.stats record --wrap-json <rawDir>/avo.wrap.json` — append to `.avo/state.json` → `stats.sessions[]`, update `stats.totals`.
7. Emit cleanup telemetry (optional `Telemetry.cleanup()` when available): bytes freed + preserved-set size.

---

## Preserved set

Cleanup is allowed only after `edit/timeline/reconstruction-bundle.json` verifies:

- Raw source file(s) in `rawDir`
- Initial transcript artifact
- Final transcript from **approved master** (`edit/transcripts/<master-basename>.*`)
- Final master output
- Canonical timeline indexes, immutable revisions/events, projection lineage
- Candidate-bound review evidence and exact approvals
- The reconstruction bundle itself

---

## Example

```text
python -m avo.cli cleanup dry-run --project /videos/review/avo.project.json --master-basename 20260814-review-master-v001
```

## Shared timeline gateway

Resolves provider/video context but performs no editorial timeline mutation. Reports and configuration reference canonical artifact/revision identities.
