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

## Report freshness

A saved map is current only while its canonical heads and bounded review inputs
still match. Generator 1.9 records the requested work, selected direction and
review context separately from the canonical picture/audio basis. Sound work
also binds the current validated catalogue generation, even when its existing
work was already stale for another reason. Refreshing this report does not
change canonical revisions, a valid compiled proof, or any approval.

Native reports remember which proposal was explicitly requested. Currentness
reconstructs that context from the project and retained metadata without media
scans, source-byte hashing, model execution or report publication. An active
request retains its frozen options; changed preferences affect future requests.
An unfrozen default view becomes historical when its effective options change.
Explicit preview context remains frozen, while current requested work and
direction are rechecked. Damaged or unavailable current inputs leave the saved
report readable as historical, with a warning.

Reports from generators 1.1 through 1.8 remain readable. They lack the new
freshness guarantee and are reported as historical. Regenerate a view to obtain
its current basis. Historical status does not invalidate unchanged selected
source media or transfer rendered, listening or creator acceptance.
