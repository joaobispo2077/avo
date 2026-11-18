# Motion direction after audio revisions

The motion map can retain an applied item's visual direction after an audio-only
revision. This permits another sound proposal against the same current visual
anchor while the overall composition remains stale.

Reuse requires the original selected motion application and unchanged selected
direction. Current CMap and Sync Map references must still match the frozen
basis, including their state. Current BMap and Tracks must be valid. The exact
Animation revision must remain selected and available; a new revision, even with
identical content, does not qualify. Blocked or superseded Animation never
qualifies.

The reader loads the retained BMap, Tracks and Animation revisions with existing
containment, immutable-hash, schema, reader-capability and byte-budget checks.
It compares the complete non-audio cue list, picture tracks, Animation body and
other visual settings. Audio lanes, music/SFX/ambience cues and refreshed parent
basis references do not change this visual comparison. A changed asset, cue,
timing, picture order, camera or other visual setting keeps the direction stale.
Only applied items with canonical visual cues qualify; untimed and unapplied
concepts cannot gain applied status through this comparison.

A unique explicit proposal `cueId` can associate a legacy canonical cue that
does not carry `contentRef.itemId`. Reuse uses the same identity rules as the
map and storyboard. Explicit canonical identity remains authoritative;
conflicting claims block every affected item, including another clean part of
an item with a conflicting split. This does not relax visual dependency checks.

The overall motion proposal and report readiness remain stale when their full
canonical basis changes. Animation's canonical stale state is preserved, and its
owner must reconcile it before rendering or approval. The map's unchanged visual
items can retain their recorded applied disposition. Sound proposals then freeze
the current heads and recompute their opportunities and fitting normally.

This is metadata reuse for planning. It performs no media decode, source-byte
hashing, optional inference or previous-proof reuse. Existing rendered evidence,
listening acceptance, composite approval and proof admission are not refreshed
or transferred. Missing or damaged retained metadata leaves items stale and adds
an explicit gap. Changing part of the visual assembly currently disables this
reuse for the whole assembly; finer intersecting-item reuse remains separate work.

Generator 1.7 keeps reports from 1.1 through 1.6 readable.
