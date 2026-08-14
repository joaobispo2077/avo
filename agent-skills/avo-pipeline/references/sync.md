# /avo.sync reference

**Audio sync diagnosis** — run early on external recorder, multicam, podcast, gameplay, or screen captures.

## Preconditions

- [ ] `provider` + `rawDir` declared
- [ ] Source tracks inventoried (camera, recorder, system audio)

## Workflow

1. Document sync method (clap, timecode, manual align, tool used).
2. Check drift at **start, middle, end** on programs >10 minutes.
3. Verify channel mapping and sample-rate compatibility.
4. Write [`docs/templates/review/sync-check.md`](../../../docs/templates/review/sync-check.md) → `<rawDir>/edit/review/sync-check.md`.

## When to run

- **Before** `/avo.trim` on external audio workflows
- **After** major structural changes — re-verify

## Handoff

- [`sound.md`](sound.md) — mix after sync anchor chosen
- [`trim.md`](trim.md) — creative cuts only after sync PASS

## Related

- AGENTS.md audio-first policy

## Generic parameter contract

Collect raw picture/audio fingerprints, selected streams and channels, reference
clock, sign convention, calibration samples across the program, transform kind
(`constant-offset`, `linear-drift`, or `piecewise`), tolerance, and residual
evidence. `positive-audio-delay` means the audio event is placed later on the
picture clock; `+128 ms` maps audio tick 1000 to picture tick 1128.

Distinguish constant offset from accumulated drift. Drift requires at least two
separated control points; piecewise correction requires strictly increasing
points. Validate start, middle, end, every join, and risk window. Missing or
over-tolerance full-program evidence blocks approval. Resync always reprojects
from raw—never stack correction on a corrected proof or delivery.

