# Cleanup preservation and truthful learndown

Native Shorts batches also resolve final exports from canonical batch delivery
manifests and nested transcript sidecars. Lookup validates project-contained paths
and transcript/master identity; it does not confer approval. Reconstruction
independently verifies media bytes. Extra footage retention continues to use
`cleanup.preservePaths`.

Cleanup verifies both hashes and coverage. A correctly hashed bundle that omits a
current canonical local media dependency is not safe to execute. Current source
fingerprints, project configuration, the renderer EDL, authoring inputs and
delivery/approval documentation must survive. A changed or missing dependency
requires a fresh bundle; do not patch a bundle to bypass validation.

One canonical cleanup invocation verifies the reconstruction graph once and uses
that freshly verified protected set for the remaining checks and deletion. It
does not import a cached receipt or waive byte and coverage validation. Separate
verification commands remain independent. A caller preparing the final wrap in
the same process can use the real cleanup result and completed execution receipt
instead of starting another full inventory merely to report those deletions.

Final-master lookup preserves the legacy `edit/masters/<basename>.*` convention.
When that location has no match, inventory, reconstruction and duration probing
share a metadata-only locator for an explicitly documented export. It reads
`edit/delivery-manifest.json` and `*manifest*.json` beneath `edit/delivery/`, using
their top-level `master.path`, `master.sha256` and `master.sizeBytes`. Relative
paths are project-relative. The requested basename, current file size and final
transcript's source identity must agree. Missing, ambiguous, conflicting,
traversing, symlinked or out-of-project references fail closed. The transcript's
source path may name a byte-identical native export; it is not the delivery
locator. An arbitrary proof is never selected by directory search or recency.

Locating a file does not confer approval, validate media bytes or advance the
pipeline. Reconstruction still checks the exact master hash and all independent
bundle gates. This fallback neither copies nor relocates exports and requires
no new project setting or public schema.

Current-media fingerprint constraints come only from the active CMap, BMap,
Tracks, Animation and Sync indexes. The iteration ledger is archival history:
different iterations may record different hashes for one reused request path.
Those historical hashes remain unchanged; they are not simultaneous requirements
on the current media. Ledger indexes, revisions and events remain in the graph.
Text and code documents beneath `edit/review/` are also preserved with their
actual current file fingerprints, without asserting that superseded historical
bytes are available. Build and verification use the same media classification;
changed active media, missing coverage and changed archived files still block.

Projects can retain additional files or directories in `avo.project.json`:

```json
{
  "cleanup": {
    "preservePaths": ["edit/review", "edit/master", "edit/animations"]
  }
}
```

Entries must exist and be project-relative. Absolute paths, parent traversal,
the project root and links escaping the project are rejected. Retention is
additive: it never removes canonical protection. Inspect the resulting dry-run
before destructive execution. Private per-video choices belong in the external
project, not in reusable orchestrator code.

Execution writes `edit/cleanup/cleanup-result.json`: intent first, actual outcome
afterward. Only files verified absent after the attempted deletion contribute to
`deleted` and `freedBytes`. Failed deletions produce an incomplete result and
prevent session-scratch purge. An existing receipt prevents silent replacement;
review it before another execution.

Final wrap in the default cleanup mode requires a completed cleanup receipt for
the same project and master basename.
It never treats remaining candidates, an old draft, or a historical inventory
diff as proof of deletion. `--freed-bytes` is an optional consistency check,
not a way to invent a result. Draft wrap files remain as audit history after
finalization. Final learning does not authorize public publication or transfer
another video's approvals or music rights.

An explicit `wrap final --closure-mode preservation --no-export` closes a project
by keeping its files. This mode requires explicit retention of the entire
`edit/` directory, successful native reconstruction verification and a real scan
with zero deletion candidates and no errors. It writes a distinct immutable
`edit/cleanup/preservation-result.json`, never a completed cleanup receipt.
`cleanupExecuted` is false and `freedBytes` is null. Even an explicit zero for
`--freed-bytes` is rejected in this mode, because no space-recovery measurement
was made. The normal cleanup mode retains its original requirements.

The preservation receipt binds the project, configuration, exact master and
transcript identities, reconstruction bundle and retained-file metadata. Its
byte-verification scope is the reconstruction graph; additional retained files
are covered by the metadata snapshot. They are not described as fully rehashed.
Later receipt validation repeats native byte checks and rejects stale metadata,
added or removed files, changed bindings, unsafe paths and receipt tampering.
The one-pass finalizer can consume its freshly verified in-process result once;
it cannot import an arbitrary cached pass. Preservation output paths reject
links and reparse points before verification and writing.

Finish canonical administrative changes and documentary files before building
the final reconstruction bundle and issuing the preservation receipt. Changes
to files inside `edit/` afterward invalidate that receipt. Root wrap outputs are
excluded deliberately to permit writing the final wrap after verification.
Do not silently rewrite a receipt or mark earlier pipeline stages passed to
resolve an ordering problem. See [existing-master adoption](native-master-adoption.md).
