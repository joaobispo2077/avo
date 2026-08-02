# /avo.stats reference

Implements local aggregate metrics from session history. Owning helper: `helpers/stats.py`.

**Privacy:** Reads `.avo/state.json` on disk only — no phone home. See [`SECURITY.md#privacy--telemetry`](../../../SECURITY.md#privacy--telemetry).

## When to use

- After one or more videos completed through `/avo.cleanup` (session recorded)
- Anytime you want cumulative productivity totals without opening wrap files

## CLI

```bash
python helpers/stats.py show
python helpers/stats.py show --json
python helpers/stats.py show --verbose
```

Session recording (agents run during cleanup, not via this command):

```bash
python helpers/stats.py record --wrap-json <rawDir>/avo.wrap.json
```

## Metric tiers

| Tier | Flag | Metrics |
| ---- | ---- | ------- |
| **A** | (default) | Videos completed, total disk freed, preserved library, last video (title + date), top provider, avg freed/video, time saved (estimated) |
| **B** | `--verbose` | Cut ratio (avg), phases per video, approval gates passed |
| **C** | `--verbose` | Estimation model id + factor (`duration-factor-v1`, default 2.5× source duration) |

Time saved is **always labelled estimated** in default output — never presented as measured wall-clock editing time.

## Canonical human output (illustrative)

```text
AVO stats (local only — see SECURITY.md#privacy--telemetry)

Videos completed:     12
Disk freed:           91.6 GB
Preserved library:    5.0 GB
Last video:           Dealer walkthrough (2026-08-01)
Top provider:         bishop (9 videos)
Avg freed / video:    7.6 GB
Time saved (est.):    ~14h (estimated, 2.5× source duration)
```

## Storage

| Path | Content |
| ---- | ------- |
| `.avo/state.json` → `stats.sessions[]` | Last 200 session detail records |
| `.avo/state.json` → `stats.totals` | Cumulative counters (survive session rotation) |
| `<rawDir>/avo.wrap.md` | Per-video audit trail on footage volume |

## Zero sessions

Print guidance to run a full pipeline through cleanup — not an error.

## Related

- Wrap artifacts: [`docs/avo-workflow.md`](../../docs/avo-workflow.md) §7
- Cleanup records sessions: [`cleanup.md`](cleanup.md)
- Privacy: [`SECURITY.md#privacy--telemetry`](../../../SECURITY.md#privacy--telemetry)
