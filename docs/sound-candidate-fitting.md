# Sound candidate fitting

`avo.timeline.sound_planning.fit_sound_candidate` is a pure fitting primitive for
the selected-sound workflow. It reads a bounded opportunity and a validated saved
catalogue entry. It does not inspect current media bytes, select an effect,
publish timing, change picture duration or approve a mix. Native proposal/apply
orchestration and actual encoded/listening qualification remain separate work.

The opportunity identifies its item/cue/event, visible frame interval, purpose
and main/bass/support/detail/tail role. The candidate requires complete acoustic
coverage, source-bound licensed-rights evidence and a reviewed native-sample
marker. Unknown visibility/rights, missing sources, stale marker evidence or
incomplete tail analysis produce unresolved results. Explicit silence is valid.

An optional `cameraAnchor` on a `camera-emphasis` intent selects a node from the
actual canonical camera component. It carries `componentId`, `pathHash`,
`sourceSha256` and zero-based `nodeIndex`, as exposed by the motion map. Supply
either this anchor or the existing cue-relative `phase`. The linked cue must
unambiguously own that component and target its picture layer. A changed source,
path, missing node or ambiguous component stays unresolved; a claimed camera in
an unapproved proposal cannot substitute for canonical Animation metadata.

The selected node's relative phase uses the camera evaluator's full cue interval,
including its final visible frame. The accent is rounded to the nearest output
frame using the existing native event clock. Window previews preserve that
absolute frame rather than restarting the camera or sound at the window edge.
This option requests an audition; static, hidden and background motion still
recommend silence and no sound is added automatically.

An optional `sourceAnchor` selects an explicit point in a fingerprinted original
through the current CMap. It carries `sourceId`, `sourceSha256`, native rational
`sourceTime: {ticks, timebase: {num, den}}`, and one exact occurrence selector:
`segmentId` for contiguous edits, or `placementId` with optional `trackId` for
placed edits. Repeated footage never defaults to the first take. Supply this
anchor instead of `phase` or `cameraAnchor`. The source point must lie inside
the retained half-open source occurrence and its mapped frame must lie inside
the linked visible cue. Missing, changed, disabled or ambiguous context remains
unresolved; it is never clamped to a cue edge. Still images and sampled picture
placements are not qualified for inverse source-point mapping.

Source anchoring reads bounded canonical metadata and reuses the native CMap
mapping and output-frame rounding. It does not infer a spoken word's timing or
approve the selected source moment. Published choices retain the anchor and
final proof admission recomputes it against current canonical metadata. Full
and window exports preserve the same absolute frame. Ordinary cue-phase events
do not request an additional source-map read.

For a selected native trim, the relative transient is:

`original marker sample - trim start sample`

The existing event clock converts that offset to output samples and schedules it
against the event's program frame. Useful attack/tail samples must remain inside
the selected trim. Insufficient pre-roll or program-tail space stays unresolved;
the primitive does not shorten a sound or extend the picture to make it fit.
Duration follows the native source clock's separately converted start/end
boundaries. The audio event carries no picture-visible range; visual context stays
on the opportunity, matching the existing native audio event owner.

The strict `avo.sound-selection.schema.json` candidate-fit document binds the
rational/output clock, program extent, source/measurement identity, current
curation/rights/marker identity and selected trim to its hash. A fit only reports
timing feasibility. Actual application must bind current canonical heads and
catalogue generation, revalidate selected source bytes, publish through BMap and
Tracks, and measure/listen to the encoded result. Listening acceptance stays
pending regardless of the calculated fit.
