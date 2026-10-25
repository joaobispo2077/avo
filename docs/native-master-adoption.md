# Existing-master adoption without copying

Adoption is an explicit administrative route for an existing approved master.
It does not re-render, copy or relocate the media, regenerate transcripts, or
replace historical editorial records. The legacy `deliver prepare` workflow
remains available with its original copy-and-review behavior.

`deliver adopt` requires the existing master, canonical assembly, persisted
delivery review and four existing transcript sidecars (JSON, TXT, MD and SRT).
It checks exact identities, current canonical heads, source-only assembly
lineage, current native candidate snapshot, actual regression results, structured
visual coverage and native gates before creating a review-ready delivery
manifest. Approval remains a separate exact-file decision. Repeating adoption
revalidates the same identity and preserves an existing delivery approval.

`review run --reuse-transcript` forbids ASR fallback. Missing, malformed, stale
or model-incompatible transcripts block the operation. A supplied runtime is
also bypassed in this mode. Existing transcript analysis still reports gaps and
term risks; reuse is not an automatic textual pass.

`review run --checkpoint deliver --adoption-review` produces the union of
motion-proof, pre-master and delivery evidence for one current master review.
The registry actually verifies current BMap, Tracks, Animation, Sync, final
transcript and source fidelity alongside the normal technical evidence. Each
native gate is evaluated over that exact evidence; missing, duplicate, stale,
failed or unresolved evidence cannot be converted into approval. Coverage and
review context must state the combined purpose. Still-frame observations cannot
certify audio or continuous motion, and a source log is not proof of a license.

Native non-cut decisions retain the original creator-acceptance artifact as a
fingerprinted reference with its historical date and scope. Registration of a
new native decision has its own current timestamp. It requires an actual
candidate-exact regression result bound to the frozen ProofPlan contract and
obligation coverage. No old approval, opaque regression hash or documentary
acceptance alone satisfies the automated gate.

Native visual review extracts its selected frames in a single decoding pass.
The PNG stream is bounded and validated, frames are mapped by selected frame
index rather than timestamp assumptions, and existing cached files must match
the fresh decode. Their fingerprints are checked again before model inference.
This preserves exact selection for both CFR and VFR sources while avoiding one
prefix decode per requested frame. Candidate hashing streams the media once;
the same measured hash is reused within that review rather than allocating the
whole export in memory. These changes affect analysis only, not the master.

## Explicit final human authority

Human-final adoption is a separate, opt-in route. It requires an immutable
`human-final-disposition` artifact tied to an explicit user decision, the exact
master identity, the original creator acceptance and the current dependency lock.
It is never inferred from an ordinary approval or enabled by default.

At the service boundary, pass `review_path=None` and
`human_final_disposition_path=<artifact>` to `DeliveryService.adopt_existing`.
The ordinary automated review and the human-final disposition are mutually
exclusive inputs. The default route continues requiring the complete automated
review and approved native snapshot described above.

The human-final route can accept an automated failure, unresolved judgment or
interrupted Watch run because the user's final review is authoritative. The
original automated reports, statuses, coverage and interruption evidence remain
fingerprinted and unchanged. No AI pass, completed coverage, regression pass or
historical candidate snapshot is manufactured. The delivery manifest identifies
`review.kind` as `human-final-disposition` and `review.state` as `human-approved`,
with a separate fingerprinted disposition reference and no synthetic
`candidateSnapshot`.

This authority does not bypass master-byte integrity, exact transcript binding,
current canonical dependencies, source-only assembly lineage or the integrity of
the referenced evidence. The four existing transcript sidecars are still
validated and preserved. Delivery approval remains a separate exact-file record;
revalidation checks the disposition again, and any changed dependency or artifact
invalidates the administrative binding. This route performs no render, ASR or
media copy and confers no publication or cleanup permission.

The administrative delivery-adoption transition preserves earlier pipeline
history. It records one explicit adoption event with current evidence rather
than inventing historical motion or pre-master review runs. Normal sequential
transitions and their requirements are unchanged. Final preservation is a
separate operation; no adoption grants publication rights or permits deletion.
