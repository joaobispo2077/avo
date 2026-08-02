# /avo.stats Command

Display local aggregate metrics from completed video sessions.

**Skill:** [`docs/avo-pipeline/references/stats.md`](../../docs/avo-pipeline/references/stats.md)

**Privacy:** Local disk only — no phone home. See [`SECURITY.md#privacy--telemetry`](../../SECURITY.md#privacy--telemetry).

---

## Usage

```
/avo.stats
```

Optional: `--json` (machine-readable stdout + `AVO_JSON` on stderr), `--verbose` (Tier B/C metrics + estimation model)

---

## Role

Read-only. Summarizes session history in `.avo/state.json`. Does not scan footage folders unless a session record points at missing paths.

---

## Instructions

1. Run `python helpers/stats.py show` (or equivalent when helper ships).
2. **Tier A (default):** videos completed, total disk freed, preserved library size, last completed video, top provider, average freed per video, estimated time saved (with disclaimer).
3. With `--verbose`: Tier B (cut ratio, phases per video, approval gates) and Tier C (full estimation model + factor).
4. With `--json`: JSON on stdout; duplicate `AVO_JSON` line on stderr (telemetry pattern).
5. Zero sessions → friendly message pointing to `/avo.pipeline` workflow; exit 0.

---

## CLI equivalent

```bash
python helpers/stats.py show
python helpers/stats.py show --json
python helpers/stats.py show --verbose
```

---

## Example

```text
/avo.stats

/avo.stats --verbose

/avo.stats --json
```
