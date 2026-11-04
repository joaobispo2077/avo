# BL-020: Motion map and storyboard review

**Status:** Research proposal, not implemented or scheduled.
**Priority recommendation:** First slice from the [reference comparison](../../docs/fluxo-de-edicao-comparison.md).
**Surface:** Extend existing motion planning/review; no new slash command required.

## Outcome

Before expensive motion work, show a chronological motion map and linked
storyboard cards alongside CMap/BMap. Each item explains the spoken idea,
treatment, camera intent, sound relationship, assets and review status. Include
clear no-motion choices and unresolved assets.

## Reuse and boundary

Join existing CMap, BMap, Tracks, Animation and selected direction. BMap keeps
cue timing; Tracks keep assembly; Animation keeps component behavior without
owning cue timestamps. Generated review views are not another timeline or a
replacement approval system. Initial concept review can precede resolved assets;
do not fabricate render-ready identities or require a completed assembly.

## Acceptance targets

- Map rows and storyboard cards share stable cue/component identities and exact
  input revisions. Optional friendly labels resolve back to those identities.
- Show time/duration, word/cut anchor, purpose, layers, entrance/hold/exit,
  camera before/during/after, reading time, asset gaps and current disposition.
- Distinguish planned sketches from actual rendered evidence. Mark stale,
  incomplete and ambiguous joins rather than guessing.
- Requests by ID produce native proposed revisions; a section decision never
  fabricates full-program or final-render approval.
- Regenerate deterministically after revisions; test stale inputs, missing
  components, cut-edge rebasing, unresolved assets and stable-ID edits.

Start with readable text and cards. A role-based audio/video lane strip and
key-state thumbnails are follow-ups, not a new editing application. Reuse
existing storyboard templates, review/invalidation services and BL-011 planning.
