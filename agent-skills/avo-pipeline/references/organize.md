# Organize and discover a footage library

## Step/state mapping

**Workflow steps:** Resolve library -> Review structure -> Run selected action -> Verify and report result
**Durable state:** external `edit/library-index.json`, immutable proposal/prepared/decision records, `edit/library/operations/<operation-id>/status.json` and native invocation results
**Approval or input gate:** Resolve missing root/provider/scope before work; for source moves or transcription, prepare the exact packet and wait for the creator's explicit decision before recording approval or executing it.
**Stop when:** Missing root/provider, stale or unsafe evidence, required explicit approval, unsupported capability, cancellation, or verified requested result
**Valid next commands:** /avo.organize, /avo.transcribe, /avo.pipeline

Follow [step-status.md](step-status.md), including its approval-prompt fields and final four-line footer. No text follows that footer. Resolve library uses declared root/provider/scope; Review structure uses the current native proposal and review; Run selected action stays awaiting user at an approval gate; Verify and report result is completed only when the requested outputs and actual outcomes are verified. A review-only request can complete without applying files or transcribing.

## Start with a visual review

Use the existing runtime: clone `python -m avo.cli organize`; installed engine `avo organize`. Both expose the same operations. Every operation requires `--root <absolute-footage-root>` and `--provider <configured-slug>`. The root must exist outside the AVO repository. Resolve the provider first; library work does not require creating a video manifest. Closed video roots reject mutations; there is no implicit reopen.

The examples use PowerShell. Set these values to the user's existing footage root and configured provider:

```powershell
$root = 'D:\Footage\library'
$provider = 'my-channel'
$scan = python -m avo.cli organize scan --root $root --provider $provider --json | ConvertFrom-Json
```

Add `--recursive` only after explicit subfolder inclusion. Inventory excludes generated edit outputs, proxies, masters and links. Default scan performs metadata probing and writes inventory/proposal/review records; it does not transcribe, watch content, upload media or move sources. It preserves valid unchanged preparation.

Show `$scan.refs.review.html` and `$scan.refs.review.text` as clickable local file links. Present a compact current/proposed folder tree, then counts, group purpose/evidence, unresolved files, conflicts and exact path changes. Expand affected groups rather than dumping the entire library into chat. Example hierarchy only:

```text
base-folder/
|-- xpto/
|   |-- camera-a/   related recordings
|   `-- camera-b/   related recordings
`-- needs-review/  unresolved assignments
```

Use actual native evidence for names/counts. Filename/folder grouping does not imply the footage was watched. The offline review supports keyboard controls, complete text and local request export. Editing/exporting that view changes neither files nor approval state. It is a snapshot; recheck native state before importing or executing.

## Import changes through native validation

The browser exports a bounded UTF-8 `kind: edits` request. Review its contents and compute the hash of the exact exported bytes:

```powershell
$changes = 'D:\Footage\library\library-requested-changes.json'
$changesHash = (Get-FileHash -LiteralPath $changes -Algorithm SHA256).Hash.ToLowerInvariant()
python -m avo.cli organize propose --root $root --provider $provider --request $changes --request-sha256 $changesHash --json
```

Use the actual export path; moving it into this example location is not required. Native edits permit `rename-group`, `assign-recording`, `exclude-recording` and `keep-recording`. They bind the current library/head, base proposal ID, integer revision and proposal hash. Stale or unknown IDs, unsafe folders and invalid mappings do not bypass validation. Import publishes a successor and new review links; old approval cannot authorize changed actions.

`review --proposal <returned-document-id>@<revision>` regenerates HTML/text for a returned proposal. Native `propose` without a request builds another proposal from the current inventory; it is not an approval or apply command. Obtain the current proposal/body and IDs through returned references, not filenames guessed from labels.

## Prepare and approve file moves

Only selected actions with status `move` can be prepared. Review a selection JSON containing exactly `actionIds` and `unboundSourceIds`, both arrays of actual returned IDs. The unbound recording IDs must exactly cover the selected actions and reflect known ownership. Do not declare media unbound merely to bypass a reference blocker.

```powershell
python -m avo.cli organize prepare --root $root --provider $provider --proposal $proposalIdAndRevision --selection $selectionFile --json
```

`$proposalIdAndRevision` is the returned proposal document ID plus its actual revision. `$selectionFile` is the reviewed selection file. Preparation hashes selected sources and returns `packetRef`, estimates and source locks without moving anything. Cold source verification may take time; do not present it as part of a warm interaction-time promise.

Before asking for approval, show the prepared file path/hash, exact mappings, selected IDs, blockers and expected impact. State why approval is needed, what it controls, accepted explicit replies and their consequences as required by [step-status.md](step-status.md). A browser export, AI pass, generic historical approval or prepared packet alone is insufficient.

After the creator explicitly decides, write the exact decision request defined by the shipped [library schema](../../../schemas/avo.library.schema.json):

| Field | Value source |
| --- | --- |
| `schemaVersion`, `kind`, `requestId` | `1`, `decision`, new request identity |
| `libraryId`, `expectedHeadHash` | Current native library state |
| `packetId`, `packetHash` | Returned `packetRef.id` and `packetRef.sha256`; use the document reference ID |
| `approvedIds` | Exact prepared action IDs; for a batch these are recording IDs |
| `decision` | Actual `approved` or `rejected` creator decision |
| `actor`, `creatorInstruction`, `createdAt` | Real reviewer identity, actual explicit instruction and its timestamp |

Hash the reviewed decision file with `Get-FileHash`, then record it:

```powershell
$decisionHash = (Get-FileHash -LiteralPath $decisionFile -Algorithm SHA256).Hash.ToLowerInvariant()
$decision = python -m avo.cli organize approve --root $root --provider $provider --request $decisionFile --request-sha256 $decisionHash --json | ConvertFrom-Json
```

Only an approved decision for that exact packet permits execution:

```powershell
python -m avo.cli organize apply --root $root --provider $provider --approval $decision.decisionRef.id --json
```

The native boundary rechecks source bytes/file identity, root/provider, ownership and destinations. Physical moves are supported only on tested fixed local Windows NTFS storage, within one root/volume, without overwrite or copy/delete fallback. Existing AVO/NLE-referenced recordings stay at registered locations. Unknown ownership, links/junctions, hardlinks, occupied targets, move chains/cycles and case-only changes are blocked. No source media is deleted automatically.

## Status, cancellation and recovery

Use the actual returned `operationId` for these commands:

```powershell
python -m avo.cli organize status --root $root --provider $provider --operation $operationId --json
python -m avo.cli organize cancel --root $root --provider $provider --operation $operationId --json
python -m avo.cli organize resume --root $root --provider $provider --operation $operationId --json
python -m avo.cli organize reverse --root $root --provider $provider --operation $operationId --json
```

Do not run these as an unconditional sequence. Inspect status first and perform only the requested action. Cancellation acknowledges a durable request and stops new item admission; an already executing move/transcription may finish. Report that item until it settles. Resume reconciles durable outcomes and current sources, rather than blindly repeating moves. Ambiguous source/destination state needs review.

`reverse` is for a previous move operation and produces a new inverse proposal. It does not move files immediately. Review, prepare, explicitly approve and apply that proposal separately; new collisions/source changes block reversal. Keep operation history intact.

## Find footage and admit existing transcripts

```powershell
python -m avo.cli organize search --root $root --provider $provider --query 'xpto' --mode all --limit 20 --json
```

Modes are `metadata`, `speech` and `all`; queries are 1..512 characters. Results default to 20 and are capped at 100, with excerpts capped at 240 characters. Continue with the returned `nextCursor` using `--cursor`; stale cursors require a fresh search. Optional filters: `--group`, `--date-from`, `--date-to`, `--min-duration`, `--max-duration` and `--transcript-status`. Missing date/duration values omitted by filters appear in coverage.

Show match evidence, current paths, source ranges, availability and speech coverage. Metadata-only entries were not searched for speech. Search does not start ASR or load the whole library into agent context. Report cache/network/FTS limitations instead of claiming unchanged performance on every volume.

Returned candidates are freshly checked, including actual transcript bytes and timing before quoting speech. Broader coverage is explicitly a saved index snapshot; show `freshnessScope`, observed/unobserved counts and any refresh recommendation. A current returned match does not imply every indexed file was restatted during that query. Selected handoff performs strong source verification separately.

An explicitly supplied existing native transcript can be admitted while scanning:

```powershell
python -m avo.cli organize scan --root $root --provider $provider --recursive --transcript "$recordingId=edit/transcripts/clip.json" --json
```

Keep the previously agreed scan scope; omit `--recursive` for a root-only library. IDs must come from that library. Transcript paths are root-relative, with current original-source fingerprints and valid timing. Admission reads evidence and revises library state; it does not run transcription. Refresh proposal/approval references afterward.

For a handoff, create a bounded `kind: handoffRequest` with the current request envelope, returned search `generation`, exact `recordingIds` and optional `ranges` keyed by recording ID (`start`/`end` in original-source seconds). The native schema caps selection at 100 recordings. Review and hash it, then use:

```powershell
python -m avo.cli organize select --root $root --provider $provider --request $selectionRequest --request-sha256 $selectionHash --json
```

Selection verifies current source evidence and retains restrictions/transcript/shared-usage references. It does not produce a BL-011 composition brief, EDL, cut, render or editorial approval. Load only evidence needed for the next explicitly requested task.

## Optional local batch transcription

Use `kind: batchRequest` with the current `schemaVersion: 1`, new `requestId`, `libraryId`, `expectedHeadHash`, exact `recordingIds`, `route: local`, an actually prepared catalog `model`, explicit `language` and `limits`. The language can be a supported code or `auto`; requested auto stays separate from detected speech language.

Required limits are `workers: 1`, positive `cpuThreads` within this machine's count and positive `maxProcessingSeconds`. Optional `maxTemporaryBytes` must permit the 67,108,864-byte per-output publication reservation; this is not a cap on total retained library size. The optional monetary object cannot enable paid processing. Paid routes and remote model endpoints are unavailable for this workflow.

```powershell
$batchHash = (Get-FileHash -LiteralPath $batchRequest -Algorithm SHA256).Hash.ToLowerInvariant()
python -m avo.cli organize batch prepare --root $root --provider $provider --request $batchRequest --request-sha256 $batchHash --json
```

Present the exact packet, selected/reusable/new counts, known/unknown duration, temporary-space reservation, model/runtime disclosure, CPU/thread limits, unknown timing and separate compute/token/charge coverage. Large or uncertain batches require the displayed warning. The current native route uses prepared local files, CPU/int8 and one worker. Preparation does not dispatch inference or upload footage. Do not substitute another model/route silently.

Obtain and record an explicit decision for the batch packet through the same `approve` flow, then run:

```powershell
python -m avo.cli organize batch run --root $root --provider $provider --approval $batchDecisionId --json
```

Use the returned decision document ID. Valid completed outputs are reused by recording/source/configuration identity, with distinct paths for duplicate stems. Source, model, engine or routing changes can invalidate preparation. Status/cancel/resume use the operation ID. The time allowance stops new admissions and allows an already admitted item to finish; it is not a hard inference kill. Resume does not reset spent allowance. Clean pauses exclude later idle time; an interrupted running checkpoint counts downtime conservatively, and a clock reset can block continuation when allowance cannot be recovered safely.

## Performance, completion and retention

While work runs, show phase, completed/discovered/total counts, elapsed time, current item and labeled approximate remaining time. Unknown totals/ETA stay unknown. At boundaries show observed free disk and footprint; avoid full rescans or global telemetry writes on every heartbeat. Automatically summarize the returned performance report, comparing available estimates with actual time and distinguishing created bytes from logically moved bytes. Include reused/skipped/failed outcomes and remaining work. Local resource consumption is not zero cost; missing tokens/charges remain unknown, and shared batch usage must not be charged once per later video.

Persistent records live under the footage root's `edit/library/`, with authority at `edit/library-index.json`. `status` returns a retention plan with exact existing `requiredPaths`, `missingPaths` and estimated size. Before an overlapping video project's normal cleanup, review and explicitly retain those concrete paths through its existing `cleanup.preservePaths` configuration. Do not automatically rewrite configuration or retain all `edit/library/` as a shortcut: disposable search cache/review files are not durable recovery evidence. Recheck the plan as new record categories appear. Preserve external admitted source transcripts as required by the reconstruction graph.

Organization itself does not run post-render cleanup. Follow [cleanup guidance](cleanup.md), [cleanup preservation rules](../../../docs/cleanup-safety.md) and the existing human/reconstruction gates. Closed receipts cannot be edited or regenerated to make organization pass. On completion link actual review, packet/handoff/transcript/report artifacts appropriate to the requested action, disclose blockers/unknown coverage and name the next valid command before the shared footer.
