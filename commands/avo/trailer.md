# /avo.trailer Command

Teaser / trailer orchestrator with retention diagnosis. Default target duration 90s.

**Skill:** [`agent-skills/avo-pipeline/references/trailer.md`](../../agent-skills/avo-pipeline/references/trailer.md)

---

## Usage

```
/avo.trailer
Provider: my-channel
rawDir: /path/to/footage
--max-duration 90
```

Optional: segment hints via `from`/`to` · `--preview`

---

## Role

Select teaser segments from approved master — **no misleading preview** — then rights → audio-qc → deliver (`trailer` profile).

---

## Instructions

1. Parse `Provider`, `rawDir`.
2. Load [`trailer.md`](../../agent-skills/avo-pipeline/references/trailer.md) and skill **`retention-diagnostics`** in Phase 0.
3. Default `--max-duration 90` unless user overrides.
4. Forbid preview of events or payoffs not in the full program.

---

## Example

```text
/avo.trailer
Provider: my-channel
The footage is at C:/Videos/long-form-doc
--max-duration 90
```
