# Footage library organization

BL-010's implementation is delivered in this checkout, with the reference performance targets verified. Full acceptance remains pending: the five-person comprehension study has not been conducted, and an existing locked dependency advisory blocks the repository's full quality gate. Measurements apply to the documented fixtures and workstation.

Use `/avo.organize` to prepare a reusable library, review a proposed folder structure, find existing recordings and optionally approve file moves or a local transcription batch. This reduces repeated preparation and supplies evidence for future editing. BL-011 composition planning remains separate; organizing does not create a brief, EDL or video render.

## Review the proposal first

Declare the configured provider and an existing absolute footage folder outside the AVO checkout:

```text
/avo.organize
Provider: my-channel
The footage is at D:/Footage/library
```

Clone equivalent:

```powershell
python -m avo.cli organize scan --root 'D:\Footage\library' --provider my-channel --json
```

Installed equivalent: `avo organize scan --root <absolute-root> --provider <configured-provider> --json`. Replace the example context with actual values. Include `--recursive` only when subfolder discovery is explicitly wanted. No video manifest or editing pipeline needs to be initialized for indexing.

The default scans metadata and generates offline HTML plus a complete text review. It starts no ASR, content watching, source move or upload. Present the returned review links and an expandable folder tree, with current/proposed paths, counts, sizes, known durations, grouping reasons, unresolved assignments and conflicts. For example, a proposal could group related recordings as follows; these names are illustrative:

```text
base-folder/
|-- xpto/
|   |-- camera-a/
|   `-- camera-b/
`-- needs-review/
```

The browser supports keyboard use, group edits and request export. Exporting a request changes no source files. Importing its reviewed bytes and SHA-256 through native `propose` validates the current library/head and publishes a new proposal revision. Metadata-only group suggestions do not claim the footage was watched.

## What the implementation supports

| Action | Result and boundary |
| --- | --- |
| Inventory/refresh | Stable recording IDs and reusable unchanged preparation; explicit missing/stale/failed evidence |
| Visual review | Current/proposed hierarchy, full mappings, accessible text and exported edit requests |
| Prepare/apply | Exact selected sources and prepared packet, explicit creator decision, no-overwrite moves within one root/volume |
| Status/cancel/resume | Durable per-item outcomes and reconciliation; cancellation stops new admission while a running item settles |
| Reverse | A new inverse proposal needing separate preparation and approval |
| Search | Bounded metadata or admitted-transcript matches with original-source ranges and coverage |
| Select | Verified recording/path/range and evidence handoff; no composition or render |
| Local transcription batch | Approved recording selection, prepared local model, language, one CPU/int8 worker and explicit CPU/time limits |

Physical apply is limited to tested fixed local Windows NTFS. Referenced AVO/NLE media remains at registered locations. Unknown ownership, closed roots, changed sources, links/junctions, hardlinks, occupied destinations, duplicate mappings and case-only moves block affected work. There is no cross-volume copy/delete fallback or implicit reopen.

New transcription is optional. Prepare the batch and show its exact selection, source locks, resolved model/runtime, reusable/new work, known/unknown duration and resource/cost coverage before asking for approval. Paid routes and remote model endpoints are unavailable. CPU thread limits cannot exceed the machine's count. The elapsed processing allowance stops new admissions; it is not a hard kill of an active inference. Resume retains spent allowance and treats interrupted downtime conservatively.

Valid existing native transcripts can be explicitly admitted with `scan --transcript RECORDING_ID=ROOT_RELATIVE_PATH`, retaining the agreed scan scope. They must match current source bytes and valid timing. Search does not transcribe missing evidence or pack the whole library into agent context. Results default to 20 and cap at 100; selection also caps at 100 recordings. Requested `auto` language is retained separately from detected language for reuse.

Search freshly checks the files and transcript text behind returned results. Coverage for the rest of the index describes its saved snapshot; refresh after changing the library. Selected handoffs verify current source bytes before supplying evidence to another editing task.

Use the [portable organize reference](../agent-skills/avo-pipeline/references/organize.md) for exact command arguments, request fields, approval flow and examples. The [command wrapper](../commands/avo/organize.md) defines the agent workflow and shared response contract.

## Performance and cost presentation

Show initial activity, current phase/item, completed and discovered/total counts, elapsed time, approximate remaining time and estimation basis. Unknown totals and estimates stay unknown. Phase boundaries observe free disk and footprint without a recursive disk scan on each heartbeat. Completion/interruption reports distinguish processed, reused, skipped and failed work; estimates versus measured time; newly created versus logically moved bytes; and outstanding work.

Local compute consumes resources even when no billable service is used. Unrecorded tokens/charges remain unknown. Shared batch usage is referenced by later video handoffs without charging the same attempt once per video. Do not infer financial or time savings from a reuse count alone.

Reference-scale targets include two-second prepared review/search response at the 95th percentile, one-second review interactions, and a ten-second unchanged refresh for 1,000 prepared files. The following measurements pass those targets on the documented reference profile and frozen fixtures. Slow/network storage and fallback search capabilities must disclose their limitations.

Measured on the verified Windows 11 reference profile with eight allocated logical CPUs and local NTFS/NVMe storage, after five warmups and 30 measured samples:

| Prepared operation | Measured p95 | Target |
| --- | --- | --- |
| Search, including native command startup and usable JSON result | 1.29 s | 2 s |
| Search during one actual local CPU/int8 transcription worker | 1.66 s | 2 s |
| Open the visible folder review | 0.17 s | 2 s |
| Review interaction | 0.10 s | 1 s |
| Refresh 1,000 unchanged playable recordings, including command startup and reporting | 6.96 s | 10 s |

Discovery uses a frozen generated fixture with 10,000 recording records and 100,000 source-timed synthetic transcript segments. Refresh uses 1,000 actual playable files and separately verifies zero repeated probes, media hashes or transcription. The transcription load performs actual local inference; these timings do not measure speech recognition accuracy or cold model/index preparation. Source, fixture, environment and complete sample distributions are retained in the external validation reports.

## Storage and cleanup

The footage root owns `edit/library-index.json` and library records beneath `edit/library/`: proposals, prepared packets, explicit decisions, operation/batch history, transcripts, handoffs and reports. Regenerated review files and the search projection are not approval authority. A library transcript is source evidence, not a transcript of an exported final master.

For a root also used as a video project, `status` presents the exact existing retention paths and footprint. Review and explicitly retain those paths in `cleanup.preservePaths` before the existing cleanup workflow. Do not preserve all disposable cache/review output or rewrite a closed receipt. Organizing never runs post-render cleanup automatically. See [cleanup preservation](cleanup-safety.md).

## Validation and remaining acceptance

Automated tests cover source/approval boundaries, interruption and reversal, real Windows no-replace moves, inventory reuse, bounded discovery, batch cancel/resume and compatibility. Offline browser review and prepared local ASR have also been exercised. Test coverage does not stand in for creator comprehension or the complete hardware/performance protocol.

The five-person comprehension exercise remains pending at the user's request; there are no claimed participant results. Reference performance passes, including actual transcription overlap and native activity/cancellation responses under one second. The existing `msgpack` 1.2.1 dependency advisory keeps the full repository quality gate blocked; BL-010 added no dependency and did not change the lockfile. Describe the feature as implementation delivered with acceptance pending, not fully accepted or released. Local execution evidence remains under `specs/013-library-organize/`; runtime and benchmark artifacts stay outside the checkout.
