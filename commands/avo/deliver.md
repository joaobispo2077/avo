# /avo.deliver Command

Full-program master QC and delivery manifest. Distinct from `/avo.audit` (scoped time window only).

**Skill:** [`agent-skills/avo-pipeline/references/deliver.md`](../../agent-skills/avo-pipeline/references/deliver.md)

---

## Usage

```
/avo.deliver
Provider: my-channel
rawDir: /path/to/footage
```

Optional: `Footage:` master path · profile: shorts | long-form

---

## Role

Run editorial, audio, visual, caption, rights, and technical QC from `AGENTS.md`. Write delivery manifest under `<rawDir>/edit/delivery/`. Require final-file transcript from exported master. Fail closed on release-blocking issues.

---

## Instructions

1. Parse `Provider`, `rawDir` (required).
2. If user passes `from`/`to`, warn that `/avo.audit` is for window QC; deliver covers the full master.
3. Load `final-qc-delivery` skill and follow [`deliver.md`](../../agent-skills/avo-pipeline/references/deliver.md) traceability matrix.
4. Do **not** label output upload-ready when any category fails.

---

## Example

```text
/avo.deliver
Provider: my-channel
The footage is at C:/Videos/review
```
