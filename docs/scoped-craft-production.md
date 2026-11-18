# Selected motion and sound production

Plan the whole film and select which chunks to inspect or produce. A scope is a
bounded, ordered partition of the complete programme clock, plus selected chunk
IDs. Chunks cannot overlap or leave gaps. The frame rate and extent must match
the current approved native cut; placed picture retains its recorded rate.

```json
{
  "clock": {"frameRate": {"num": 24, "den": 1}, "programEndFrame": 240},
  "chunks": [
    {"chunkId": "opening", "startFrame": 0, "endFrameExclusive": 120},
    {"chunkId": "answer", "startFrame": 120, "endFrameExclusive": 240}
  ],
  "selectedChunkIds": ["answer"]
}
```

The chunk containing an item's canonical start owns its production. An item
intersecting another selected chunk stays available there as context, with its
original complete parts and absolute timing. A split item is counted once, from
its earliest start. Fractional starts remain rational numbers; they are not
rounded into another owner. Untimed or ambiguous items remain unresolved.

Use `contentRef.itemId` for canonical identity. A unique explicit proposal
`cueId` can also link an existing cue without rewriting its body. Canonical
identity takes precedence. Conflicting claims remain visible in the map and
storyboard and block scoped publication.

## Inspect and publish the view

```text
avo cli animation plan-show --project <absolute avo.project.json> --scope-request <absolute scope.json> --json
avo cli animation plan-publish --project <absolute avo.project.json> --scope-request <absolute scope.json> --json
```

Native, engine and MCP plan tools share these options. Scope requests use the
existing 1 MiB reader and reject duplicate keys, non-finite values and invalid
partitions before project access. Inspection reads metadata only. Text and HTML
show production owners, context consumers, unresolved ownership and coverage.
The whole map and linked storyboard remain available by default.

The view grants no approval. Proof rendering retains the complete canonical
graph and evaluates camera/audio against original absolute time. A context item
does not disappear from that graph because another chunk owns its production.

## Apply selected motion

Put the same scope object in the existing `plan-apply` or `camera-apply` request
as `productionScope`. The ordinary immutable request, selection, head guards,
owner preflight and source-preservation controls still apply. No separate
execution permission is created by a scope view.

An existing BMap must be valid and bound to the exact current cut. Rebase an
unresolved parent through its existing owner before selected production; a
section request cannot clear a whole-parent stale state.

Only selected items owned by the selected chunks may change. Other cues,
components and shared layers remain protected. A retimed item also requires its
previous canonical start chunk; selecting both chunks permits the move. A new
item can acquire timing through the explicit authoring payload. Context-only
scope cannot publish it on behalf of its owner.

Scoped receipts freeze the exact plan, expected heads, request hash and actual
`appliedItemIds`. A first-section publication leaves later selected items
pending, and a later publication completes only its own IDs. Current review
marks the applied items separately. Replaying an older operation does not
replace a newer selector or add duplicate revisions. Earlier unscoped receipts
retain their original full-request interpretation.

The existing run holds at most 500 typed motion application references, with a
capacity check before publication. Detached requests, duplicate receipts and
aliased paths fail validation. Existing bounded evidence retention preserves
the exact requests, decisions, receipts and canonical revisions for restart and
reconstruction. No additional project-state store is introduced.

Generator 1.8 reads 1.1 through 1.7 reports. Scoped receipts and scope summaries
use strict additive contracts; older readers that cannot interpret the added
metadata must reject it rather than infer full completion or approval.

## Apply selected sound

Add the same optional `productionScope` partition to the existing native
`sfx apply` or MCP `avo_sfx_apply` request. Keep the ordinary explicit event
choices, source admission, owner permissions and exact-byte confirmation.
The partition must match the frozen proposal's native programme clock.

A sound contribution belongs to the chunk containing its actual scheduled
audio start. For example, a whoosh starting before a visual reveal belongs to
that earlier chunk, even when the reveal lands in the next section. Sample
boundaries stay exact rational frame positions; section boundaries never trim
attacks or tails or reset their phase. The complete canonical graph remains
the proof source, including contributions owned by other sections.

A replacement requires the previous and new start chunks when they differ.
Silencing an existing effect requires its original audio owner; a new explicit
silence decision uses its visual anchor and schedules no audio. If a retired
effect's programme clock no longer matches, use the existing explicit unscoped
removal request instead of guessing a new owner. Existing per-event requests
without a chunk scope keep their original meaning.

The sound receipt freezes the partition, expected heads and one contribution
record per selected event. Each record retains current and previous complete
audio intervals and their selected consumers. Replaying or retaining that
receipt recomputes ownership from the original immutable request, choices and
parent Tracks. A changed or missing scope cannot claim another chunk's work.
The parent BMap must be valid on the exact current cut before a new scoped
application. Existing staged receipts handle interrupted publication normally.

Creator suitability, continuous visual QC, combined mix measurements, listening
and full-programme acceptance remain separate from this ownership evidence.
