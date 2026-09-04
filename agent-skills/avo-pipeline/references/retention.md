# /avo.retention reference

## Step/state mapping

**Durable state:** the consumed approved artifact, delivery-manifest.json when present, and the observed result

**Workflow steps:** Validate retention prerequisites → Run retention → Verify and report the retention result

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing required input, a failed or stale gate, a required human decision, or verified retention completion

**Valid next commands:** /avo.trim or /avo.motion

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
