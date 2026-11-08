# BL-023: Local SFX library metadata and event matching

**Status:** Research proposal, not implemented or scheduled.
**Surface:** Existing media/sound workflows; coordinate with BL-010 library work.
**Source:** [Reference comparison](../../docs/fluxo-de-edicao-comparison.md).

## Gap and outcome

AVO already has audio layers, mixing, synthetic effects, a shared event clock,
transient offsets, cached onset analysis, reviewed manual markers,
leading-silence trimming and exact-export verification helpers. Extend asset
discovery with a local, licensed SFX catalogue and inspectable matching
recommendations. Do not add a
second timing system or equate footage transcript search with SFX search.

## Acceptance targets

- Catalogue source fingerprints, license/attribution, category/material,
  measured useful duration, onset/attack/peak candidates, loudness/peak,
  optional brightness, variants and creator favorites.
- Distinguish measured envelope peaks from a human-confirmed perceptual sync
  point; reuse the existing waveform analyzer/cache and reviewed markers before
  adding analysis. Expose uncertainty and allow explicit offsets.
- Recommend by event purpose, visibility, material, available pre-roll and next
  event, then schedule through existing exact frame/sample mappings.
- Show repeats, collisions, stale sources and missing suitable assets. Missing
  sound can remain silence; no automatic effect for every cut or zoom.
- Preserve speech priority, current gain/ducking policy and existing restrictions
  on stacked overlay effects. Layering requires explicit purpose and approval.
- Test changed assets, insufficient pre-roll, sample-rate conversion, collisions,
  stale events and actual encoded alignment; creator listening remains required.

Start with file metadata and simple filters. Semantic audio/text search such as
CLAP is optional later work, not a required dependency for the first slice.
