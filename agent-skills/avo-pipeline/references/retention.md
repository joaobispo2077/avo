# /avo.retention reference

Retention and pacing **diagnosis only** — no render, no timeline edits without user approval.

## Preconditions

- [ ] `provider` + `rawDir` declared
- [ ] Transcript and/or approved structure available for review

## Load skill

- **`retention-diagnostics`** — classify dips/spikes, promise mismatch, repetition, confusion (do not overfit one metric)

## Workflow

1. State title/thumbnail promise vs current structure.
2. Map setup → evidence → payoff; flag empty hooks or misleading previews.
3. If analytics supplied, compare similar videos before inferring causality.
4. Write findings to `<rawDir>/edit/review/retention-notes.md` or project notes — **no release-blocking PASS/FAIL** unless user requests gate.

## Related

- Trailer orchestrator Phase 0: [`trailer.md`](trailer.md)
- Editorial rules: [`AGENTS.md`](../../../AGENTS.md) retention without manipulation
