# BL-012 — `/avo.voiceover` v1

**Status:** Shipped (Wave B)  
**Slash surface:** `/avo.voiceover`

## Summary

Lite path: concat clips + user-supplied voiceover + EQ/loudness. ~720p preview gate. TTS deferred to v2 (BL-003).

## Spec

[`specs/active/avo-capabilities-roadmap/spec.md`](../active/avo-capabilities-roadmap/spec.md) — FR-B3

## Engine

- EDL: `audio.program_mode: external_voiceover`, `audio.voiceover_source`
- CLI: `python -m avo.voiceover edit/edl.json --preflight-only`
- Render: video-only segment extract + `mux_external_voiceover` + loudnorm
- Review: `docs/templates/review/voiceover-gate.md`
