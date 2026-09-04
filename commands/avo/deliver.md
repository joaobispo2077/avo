# /avo.deliver Command

**Timeline integration:** Consumes

## Workflow guidance

**Workflow steps:** Validate deliver prerequisites → Run deliver → Verify and report the deliver result
**Step state source:** delivery-manifest.json and current review/approval records
**Stopping conditions:** Missing required input, a failed or stale gate, a required human decision, or verified deliver completion
**Valid next commands:** /avo.learndown

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

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

## Exact delivery gate

Delivery fails closed unless lineage, dependency hashes, candidate evidence, and
human approval all match the exact master bytes. The exported master receives a
fresh final-file transcript and post-encode technical/audio/visual QC; a
transcript or approval from a proof cannot transfer across a re-encode.

At `pre-master` and `deliver`, pass the strict v1.1 assembly record with
`--materialization`. A candidate path plus ad hoc hashes is insufficient. Build
that record with `avo tracks render --render-contract <json>` and optional
`--fidelity-policy <json>`. The candidate must match its declared profile and
actual picture-carrying ancestry; missing or stale lineage blocks rather than
passing by inference. See [`docs/delivery-fidelity.md`](../../docs/delivery-fidelity.md).

## Shared timeline gateway

Resolves provider/video context and reads only exact approved lineage. It performs no canonical timeline mutation.
