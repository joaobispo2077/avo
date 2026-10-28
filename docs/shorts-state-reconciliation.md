# Shorts state reconciliation across plan revisions

Changing one candidate must not erase the review state of its unchanged siblings.
When a resolved plan changes, AVO verifies the previous plan referenced by the
status document before retaining any item evidence. Batch identity, source,
provider tokens, output contract and canonical batch root must still match.

Items with the same input fingerprint retain their complete prior state and
exact-candidate approvals. Changed items start dirty, without inheriting artifact
or approval claims, while keeping revision watermarks so old renders cannot be
overwritten. A missing or unverifiable previous plan causes conservative
invalidation. Changes to the shared output contract invalidate all item approvals.

Batch approvals, aggregate QC and delivery completion are always regenerated for
the new plan; item approval retention never approves the new batch or a newly
rendered candidate. Artifact hashes, source-fidelity implementation locks and
exact-candidate review checks still apply at their existing gates.

This is an internal state-handling correction. CLI arguments and document schemas
are unchanged. Regression coverage lives in `test_shorts_batch_integration.py`.
