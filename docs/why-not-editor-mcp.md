# Why not a native video-editing MCP?

**Audience:** driving agents and contributors. **Not** user marketing — see
[`../README.md`](../README.md) for the human-facing summary.

## Decision record

AVO is an **orchestrator** across best-in-class local engines (transcribe, cut,
grade, motion, verify, deliver). It is **not** a thin wrapper around one
editor's timeline API.

Native editor MCPs (CapCut, DaVinci, Premiere-style integrations, etc.) optimize
for **manual timeline control inside one application**. AVO optimizes for
**agent-driven, multi-engine workflows** with inspect/fix/verify gates and
provider-scoped learning.

## When an editor MCP is the right tool

Use a native editor MCP when the primary job is:

- Frame-accurate timeline edits inside that editor's project model
- Leveraging editor-specific effects, transitions, or proprietary codecs the
  orchestrator does not own
- Human-in-the-loop review that stays entirely inside one NLE UI

That is a valid product category. AVO does not replace it.

## When AVO is the right tool

Use AVO when the primary job is:

- **Mass production** — same provider (channel/account), many projects, repeatable
  pipeline
- **Conversation-driven workflow** — strategy confirmation, iteration, memory across
  sessions
- **Composable engines** — swap transcribe/render/motion/verify tools without
  rewriting the orchestration contract
- **Confidence-gated iteration** — cheap passes (≈360p edit proof, ≈720p motion
  proof) before full-resolution render
- **Inspect → fix → verify LOOP** — watch-skill gates promotion; failures loop
  back to fix, not to re-pitch
- **Local-first, inspectable artifacts** — EDL, transcripts, slot renders, logs under
  external `<rawDir>/edit/`; no vendor lock-in to one editor binary
- **Provider-scoped identity** — brand, design, routing, and learning resolve from
  `providers/<name>/` + per-video `avo.project.json`

## Design constraints AVO encodes (not optional sugar)

| Mechanism | Purpose |
| --- | --- |
| Provider + `rawDir` declaration | Workflow root is external footage; repo holds orchestration only |
| `providers/<name>/DESIGN.md` | Brand/design lives under provider, never repo root |
| Confidence gate | Avoid full-cost renders until LOOP passes at lower resolution |
| Preserved-set cleanup | After master: keep raw, initial transcript, final transcript, master only |
| `AGENTS.md` + `docs/avo-workflow.md` | Canonical agent contract; skills defer here |

## Composability vs single-stack MCP

An editor MCP typically exposes **that app's** primitives: tracks, clips, effects.
AVO exposes **pipeline stages** and helper contracts (`helpers/transcribe.py`,
`helpers/render.py`, HyperFrames slots, etc.). Stages can be upgraded independently
(e.g. faster-whisper model tier, HyperFrames vs Remotion slot) without migrating
the whole timeline into a new vendor.

Paid or hosted options may exist per stage; nothing forces a single vendor stack.

## Agent checklist — before recommending editor MCP instead

- [ ] User needs only in-app timeline control with no cross-engine automation
- [ ] No requirement for provider-scoped batch production or external `edit/` layout
- [ ] No requirement for confidence gate / watch-skill LOOP
- [ ] User explicitly prefers one NLE and accepts vendor lock-in

If any item fails, default to AVO orchestration (this repo) and document which
stages map to which helpers.

## Related docs

- [`avo-workflow.md`](avo-workflow.md) — full pipeline, telemetry, LOOP, cleanup
- [`../AGENTS.md`](../AGENTS.md) — canonical rules including AVO Orchestrator section
- [`../install.md`](../install.md) — setup contract
- [`../providers/_template/`](../providers/_template/) — provider scaffold
