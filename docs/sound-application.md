# Selected sound publication

`SoundPlanningService.apply` is the publication boundary for explicit
per-event selections. It owns BMap and Tracks only, through their existing
services and timeline writer. Selecting a sound records pending listening;
it does not approve the mix or change picture, dialogue, music, or Animation.
Native `sfx apply` and MCP `avo_sfx_apply` share this service and the strict
`avo.sound-selection.schema.json#/$defs/applyRequest` contract. MCP confirmation
binds the exact request bytes and the native reader rechecks that binding before
project/source work. The command is a canonical write; it does not scan the
catalogue or execute a semantic model. Sound ownership is checked against the
existing command registry for both BMap and Tracks.

A strict request names the exact proposal, expected canonical heads and library
generation, actor, reason, choices and current visual contexts. Publication
requires enabled frozen sound options and unchanged authorial direction. Every
selected source must still match its indexed bytes, measured sample rate and
channel count. An explicitly injected probe records the actual first audio
stream index; metadata proposals never construct or execute that probe.

The service freezes the reviewed asset, rights, marker, source trim, output
sample schedule, channel routing and mix settings. Each contribution has one
Tracks layer and an exactly bound BMap cue, with `tracks-native` playback
ownership. Reader validation rejects duplicate identities, mismatched source or
context admission, altered schedules, secondary gain/fades, and unapproved
stacking. Historical metadata prototypes without stream/context admission stay
inspectable and cannot provide complete render admission.

Changes address stable event IDs. Replacing a sound or changing its level keeps
its layer/cue identities; selecting silence removes that contribution without
probing an asset. Other sound selections and unrelated picture/audio layers
remain intact. Multi-effect groups require the exact ordered event list.
Adding a second effect cannot borrow approval from a preserved ordinary single
effect: changing that effect's context requires explicit reselection.

An explicit silence choice can also retire a previously owned event whose visual
anchor is now absent or unresolved. The receipt retains its historical timing
only to identify the removal, without scheduling playback on the new programme.
An already absent owned audio cue is permitted only for the explicitly removed
event; a present cue must still match the exact source, choice and application.
Unknown events cannot claim this exception. Remaining ordered siblings keep their
recorded contexts and approvals. Replay checks the original immutable Tracks
parent instead of relying on a layer that has already been removed.

Sequential programme clocks use the native renderer's cumulative frame rounding,
including fractional rates and the existing precise-import policy. Placed edits
retain their canonical frame rate and integral frame boundaries. A rounded final
picture frame does not expand the approved CMap duration for audio cues.

All source, clock, role and preparation checks precede canonical publication.
Content-addressed requests, initial prepared revisions and linked receipts
record staged, committing, committed or recovery-needed state. A blocking
pending marker protects partial BMap/Tracks publication. Exact retries reuse
prepared revisions and verify actual published history; they never duplicate
contributions. Recovery rechecks the remaining canonical heads, current library,
source admission, direction and options. A failure while saving recovery
information retains the marker and reports the original error plus persistence
diagnostics. An interrupted initial operation record can be restored from its
verified staged receipt before publication.

Completed replay is historical evidence, not a new source scan or approval.
Results include actual committed heads, current heads and `headsCurrent`.
An operation's actual published parents may make unchanged descendants stale.
Finalization and exact recovery accept that expected state change while checking
the original revision, fingerprint and approval identity. They leave the
descendants stale and never publish or approve a replacement Animation plan.

Normal proof compilation derives active selected sound from current Tracks and
its actual committed publication, verifies the exact BMap binding and current
visual timing/role, and adds the contribution once. Changed or omitted sound,
unpublished admission and overlapping copies of the same sound fail validation.
Original dialogue/music processing remains intact. Native source descriptors
declare original ancestry explicitly; existing media-input checks still verify
the source. Cut proofs keep the source-only audio pass. Explicitly muted choices
do not require their unused library source to preview.

Optional ducking follows a current unmuted dialogue layer's source and selected
channels, including a single selected microphone duplicated to stereo. Missing,
wrong-channel or ambiguous stream routing fails rather than choosing another
microphone. Proof planning performs metadata validation; physical source checks,
native execution and contextual listening remain separate requirements.

Successful propose/apply operations automatically publish the current motion map
and linked storyboard. Opportunities link to their exact saved proposal; selected
sound links to its event, visual cue, audio layer, source entry and application.
The view labels proposed/authored metadata separately from listening acceptance.
Stale proposal opportunities are unresolved rather than current auditions;
malformed or foreign-project context is reported as a gap. Sound links never
extend a visual cue's timing. Default inspection stays read-only and needs no
source hashing, decoding or model. Presentation failure keeps valid publication
and returns a warning. Reports from generator versions 1.1 through 1.3 remain
readable alongside the current 1.5 generator, including older 1.4 reports.

An applied motion plan projects against its verified committed heads while
preserving the immutable proposal's original planning basis. Its own publication
therefore remains current for subsequent sound suggestions. Changed canonical
revisions, stale dependencies or changed selected direction still require review;
neither a regenerated map nor an application receipt supplies rendered or
listening acceptance.

Recoverable errors include the exact receipt reference, actual committed heads
and publication state. `recovery-needed` requires reconciliation of the saved
request; `committed` means publication succeeded and its pending marker needs
cleanup. Neither state grants listening or creator approval.

Cleanup and reconstruction retain selected canonical/history sound proposals,
their actual operation requests, immutable receipt chains, prepared revisions,
direction dependencies and pending recovery inputs through the existing bounded
motion ledger. Explicitly requested pending work also retains its verified
proposal dependencies. Unregistered drafts and generated review caches are excluded.
Source media admission and contextual listening remain distinct requirements.

Selected proposals also retain their immutable catalogue generation and verify
each chosen entry against it. Unfinished publication retains the exact current
generation selector needed for recovery. Stale pending state retains both its
frozen and currently selected generations without approving the changed basis.
A committed operation waiting only for
marker cleanup keeps its frozen generation without adopting later curation.
Catalogue metadata uses the shared 16 MiB catalogue limit inside the existing
64 MiB total evidence budget; motion documents keep their smaller individual
limit. No catalogue media or embedding cache is read or retained by this ledger.

Verified application selectors also preserve staged selections if interruption
precedes the operation record or pending marker. Their typed request, proposal,
catalogue and prepared receipt remain available for an exact retry. Discovery is
limited to the owned selector directory and the existing evidence file budget.
Generic reconstruction excludes the typed sound draft collections and then adds
the verified closure; creator notes beside those collections remain authoring
inputs.

Selected external sound files use the existing reconstruction `externalSources`
contract and the same source identity as native sound compilation. Current and
still-staged selections record their exact locator, SHA-256 and byte count;
reconstruction verifies those originals without copying or decoding the library.
Project-local selected or still-staged sound assets join the fingerprinted bundle
files, including assets not yet referenced by a published timeline head.
Missing or changed selected originals block reconstruction. This file coverage
does not grant rendering admission or listening approval.
