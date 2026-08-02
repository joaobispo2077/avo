# /avo.cleanup Command

Delete run scratch files; preserve the invariant four artifacts; write **final wrap** and record session stats.

**Skill:** [`agent-skills/avo-pipeline/references/cleanup.md`](../../agent-skills/avo-pipeline/references/cleanup.md)

---

## Usage

```
/avo.cleanup
Provider: my-channel
rawDir: /path/to/footage
```

Optional: `--dry-run` (list deletes only)

Prerequisite: **final master approved**; run `/avo.learndown` first when ai-memory is installed.

---

## Role

Workflow §7 step 2. Cross-platform `rimraf` deletes. **Release-blocking:** preserved set must survive. Records session for `/avo.stats`.

---

## Instructions

1. **Verify preserved set (REQUIRED):** `python -m avo.project_inventory verify --raw-dir <rawDir> --master-basename <stem>` — refuse if any artifact missing.
2. **Dry-run (recommended):** `python -m avo.project_inventory cleanup --raw-dir <rawDir> --master-basename <stem> --dry-run` — list delete candidates only.
3. **Execute cleanup (REQUIRED):** `python -m avo.project_inventory cleanup --raw-dir <rawDir> --master-basename <stem> [--session-id <id>]` — verify → assert no preserved paths in delete list → `npx rimraf`. When `--session-id` is set, purges `.avo/tmp/learndown/<session-id>/` after success. **Abort** if intersection non-empty.
4. **Final wrap (REQUIRED):** agent summary + `python -m avo.wrap final --raw-dir <rawDir> --master-basename <stem> --summary-file <path> [--session-id ID]` → `<rawDir>/avo.wrap.md` + `avo.wrap.json` with `status: "final"`. Retain `avo.wrap.draft.*`. Updates the provider learndown entry and `index.json`.
5. **Record session (REQUIRED):** `python -m avo.stats record --wrap-json <rawDir>/avo.wrap.json` — append to `.avo/state.json` → `stats.sessions[]`, update `stats.totals`.
6. Emit cleanup telemetry (optional `Telemetry.cleanup()` when available): bytes freed + preserved-set size.

---

## Preserved set (exactly these)

- Raw source file(s) in `rawDir`
- Initial transcript artifact
- Final transcript from **approved master** (`edit/transcripts/<master-basename>.*`)
- Final master output

---

## Example

```text
/avo.cleanup
rawDir: /videos/review
--dry-run
```
