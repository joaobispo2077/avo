# Preservation-only final closure

Preservation closure retains the whole configured `edit/` scope. It does not
execute cleanup, copy a master, or report freed bytes. Its receipt records
`cleanupExecuted: false`, zero delete candidates, and `freedBytes: null`.

Complete all authorized delivery, lifecycle, learning, and documentary mutations
before the final reconstruction bundle. Administrative archiving is a lifecycle
event, not evidence that byte verification has already completed. Do not report
final closure until the preservation receipt and final wrap exist successfully.

Use this final sequence:

1. Complete the authorized administrative archive event and all bundled changes.
2. Build the final reconstruction bundle once.
3. Call `finalize_preservation_wrap` once. It verifies every declared bundle file
   against freshly read bytes, checks retention and zero delete candidates, then
   records the distinct preservation receipt and writes the final root sidecars.

The final wrap reuses only the validated result returned within that same call.
It does not trust an unchecked prior receipt. A later independent verification
still rereads the bundle files; there is no persistent fingerprint cache.

Root `avo.wrap.*` files are output sidecars, excluded from the reconstruction raw
source list consistently with the inventory service. Updating these sidecars
must not invalidate the bundle they summarize. Canonical indexes, pipeline state,
source media, final master, transcript, review evidence, and authoring inputs
remain within their existing reconstruction coverage.

For an existing master accepted through explicit human-final authority, the
delivery manifest's native disposition in `edit/timeline/approvals/` and its
fingerprinted JSON references are required bundle inputs. This includes the
original user decision, earlier creator acceptance, and the recorded QC,
transcript and Watch outcomes even when their status is failed or incomplete.
Their bytes and continued coverage are verified; their outcomes are not changed
to automated approval. This follows only the selected authority's references,
not every historical approval or the whole cleanup directory.

Within one verification call the master uses the fingerprint obtained in the
declared-file loop, avoiding a second read of the same master. The separately
declared master must match that verified file entry in path, SHA-256, and size;
an absent or mismatched entry fails closed. The final transcript must still bind
to that verified master hash. Identical size or modification time does not
replace byte verification.

Do not archive again or modify bundled inputs after sealing the receipt. Such a
mutation requires new current evidence rather than treating the old receipt as
a reusable pass. Cleanup execution and its deletion receipt remain a separate
mode with their existing requirements.
