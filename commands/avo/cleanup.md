# /avo.cleanup Command

Delete run scratch files; preserve the invariant four artifacts.

**Skill:** [`docs/avo-pipeline/references/cleanup.md`](../../docs/avo-pipeline/references/cleanup.md)

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

Workflow §7 step 2. Cross-platform `rimraf` deletes. **Release-blocking:** preserved set must survive.

---

## Instructions

1. Verify preserved set exists: raw file, initial transcript, final transcript (from master), final master.
2. List all other paths under `<rawDir>/edit/` created by the run.
3. Refuse to delete anything in the preserved set.
4. Execute rimraf (or `--dry-run` list). Report bytes freed.
5. Emit final telemetry with preserved-set size.

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
