# /avo.retention Command

Pre-publish retention diagnosis — no render. Wraps `retention-diagnostics`.

**Skill:** [`agent-skills/avo-pipeline/references/retention.md`](../../agent-skills/avo-pipeline/references/retention.md)

---

## Usage

```
/avo.retention
Provider: my-channel
rawDir: /path/to/footage
```

Optional: analytics export path · draft structure notes

---

## Role

Diagnose structure, promise, pacing risks before edit lock or trailer cut. Does not modify timeline.

---

## Instructions

1. Parse `Provider`, `rawDir`.
2. Load [`retention.md`](../../agent-skills/avo-pipeline/references/retention.md) and **`retention-diagnostics`**.
3. Output diagnosis only — no fabricated fixes without user approval.
