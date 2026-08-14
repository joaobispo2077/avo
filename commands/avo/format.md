# /avo.format Command

**Timeline integration:** Consumes

YouTube format diagnosis stage before editing.

**Skill:** [`agent-skills/avo-pipeline/references/format.md`](../../agent-skills/avo-pipeline/references/format.md)

---

## Usage

```
/avo.format
Provider: my-channel
The footage is at C:/Videos/my-edit
```

---

## Instructions

1. Parse `Provider` and footage location (`rawDir`).
2. Follow [`format.md`](../../agent-skills/avo-pipeline/references/format.md).

## Animation library integration

Produces the required format/viewer/promise/density/risk diagnosis used before animation pattern recommendation. Recommendations remain optional and record accept, modify, or reject.

## Shared timeline gateway

Resolves provider/video context and reads only exact approved lineage. It performs no canonical timeline mutation.
