# Requested motion and sound work

Successful motion and sound proposals retain an exact work reference in the
existing pipeline run. The reference records the original frozen request,
operation, proposal hash and requested item/event IDs. It does not select an
asset, change a canonical timeline, advance a stage or approve a result.

The default motion map and linked storyboard expose these records under
`pendingRevisions`, including completed work. A fresh process can distinguish
awaiting selection, selected but unapplied motion, partial sound decisions,
recovery needed, completed choices and unavailable evidence. Actual immutable
decisions and published receipt history determine progress; a completed-stage
label or a bookmark cannot establish that an edit was applied.

Currentness is separate from completion. The view compares exact canonical heads,
their active state, selected direction, active frozen request and sound catalogue
generation. A later change keeps the original work visible with a stale basis.
Changed preferences do not rewrite an existing request. A completed historical
choice remains historical evidence and supplies no new rendering or listening
approval. Inspection does not verify physical source bytes.

Missing or damaged evidence produces an unavailable record with its original
requested item/event IDs and an explicit gap. The reader never invents completion
or repairs immutable files. Retry an interrupted publication with its exact saved
request; an unresolved or stale proposal needs a deliberate new proposal or
decision through its existing owner.

Creating another proposal preserves older pending choices. Explicit queue
decisions can defer, dismiss, reopen or supersede selected unresolved IDs:

```text
avo cli pipeline work-decide --project <absolute avo.project.json> --video-id <id> --request <absolute decision.json> --json
```

MCP `avo_pipeline_work_decide` shares the same service. The strict request uses
`avo.editing-craft-run.schema.json#/$defs/workDecisionRequest`. Copy the exact
`kind`, `operationId`, `requestId`, `proposalRef` and `scope` from the work record
into `work`; provide a fresh decision `operationId`, actor/reason, selected `ids`,
and `status`: `pending`, `deferred`, `dismissed` or `superseded`.
`expectedDecisionHash` equals the record's `decisionHead`, initially null.
Supersession also supplies an exact registered `replacement` of the same kind.

These decisions manage the production queue. They preserve chosen concepts,
applied media and approvals. Already fulfilled IDs require their normal canonical
revision controls. Deferred IDs remain visible; closed IDs are distinct from
actual completed contributions. A mixed request exposes its remaining scope.
Reopening puts unresolved IDs back in the queue and does not refresh stale inputs.
Unavailable evidence or partial publication must be restored/reconciled first.

At most 500 decision records retain exact request hashes, predecessor decisions,
actor, reason and time in the existing run. Conflicting operation IDs or stale
decision heads fail before mutation. Replaying an older exact decision reports
its historical result without replacing a newer decision. Requests use the shared
1 MiB bounded reader, including duplicate-key and optional exact-byte checks
before project access. The command avoids execution setup and publishes the
updated review; presentation failure preserves the saved decision.

The run retains at most 500 typed work references. Existing bounded motion/sound
evidence readers validate their exact operations, project ownership, original
scope, catalogue metadata and receipts. Requested pending proposals and their
verified dependencies join reconstruction alongside selected history. Unregistered
drafts and generated review pages remain disposable. Media is neither copied nor
admitted by retaining a request.

Canonical head guards inspect canonical metadata directly. They do not regenerate
the derived work view, scan application history or acquire a source/model
capability. Report regeneration remains read-only. Generator 1.6 keeps older
1.1 through 1.5 reports readable.
