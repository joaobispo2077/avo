# /avo.telemetry Command

Emit phase-boundary telemetry for the current project.

**Skill:** [`docs/avo-pipeline/references/telemetry.md`](../../docs/avo-pipeline/references/telemetry.md)

---

## Usage

```
/avo.telemetry
rawDir: /path/to/footage
phase: 4
total: 6
label: motion-proof
```

Optional: `--json` (machine-readable line only)

---

## Role

Reporting only. Implements workflow §5: disk free, step bytes, cumulative footprint, progress, rough ETA.

---

## Instructions

1. Resolve `rawDir` volume; measure free disk.
2. Sum bytes under `<rawDir>/edit/` (exclude raw sources if outside edit/).
3. Emit **human line** and **JSON line** per workflow canonical shapes.
4. Label ETA as rough estimate; never promise wall-clock accuracy.
5. Optionally probe hardware via `src/avo/hardware.py` when on render/watch phases.

---

## Example

```text
/avo.telemetry
rawDir: /videos/review
phase: 3
total: 7
label: edit-proof-watch
```
