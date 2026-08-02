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
