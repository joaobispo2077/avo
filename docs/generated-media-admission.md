# Historical-output checks during generated-media admission

Generated-media admission rejects prior proofs, previews, proxies, masters and
delivery outputs as contributing sources, including copies under new names.
It checks both retained output files and immutable historical materialization
records. These checks can otherwise reread the same unrelated previews for each
generated asset in every validation window.

The generated-asset service supplies a lazy inventory function to shared media
admission. Admission first enumerates its contributors, generated-asset records
and their complete recursive input closure. When every inspected fingerprint has
a valid byte length matching its existing regular file, inventory can exclude
historical files of different lengths. This uses length to rule out equality,
never to establish identity or reuse a previous hash.

Missing or invalid sizes, absent files, stale lengths and one-shot input
iterators fall back to the complete scan. Input iterators remain unconsumed for
the actual admission walk. Callers supplying an ordinary output list retain
their existing behavior. Inventory without complete candidate context also
retains its unfiltered default.

Each admission re-enumerates historical paths and freshly hashes matching-size
files in an independent fingerprint stage. Same-size changes with restored
timestamps remain detectable. Historical materialization hashes are included
regardless of the size filter or whether the output was renamed or deleted.
Existing original-source, generated-input, lineage and closing checks remain
authoritative. No new CLI option or public document schema is introduced.

The optimization does not provide an atomic filesystem snapshot against
concurrent writers. Source-preservation locks and the normal final validation
still apply. Regression coverage includes copied and deleted outputs, recursive
generated ancestry, incomplete metadata and one-shot inputs.
