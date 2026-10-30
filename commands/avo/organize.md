# /avo.organize Command

**Timeline integration:** Admin

## Workflow guidance

**Workflow steps:** Resolve library -> Review structure -> Run selected action -> Verify and report result
**Step state source:** external `edit/library-index.json`, referenced proposal/prepared/decision documents, operation status and the observed native result
**Stopping conditions:** Missing root/provider, stale or unsafe evidence, required explicit approval, unsupported capability, cancellation, or verified requested result
**Valid next commands:** /avo.organize, /avo.transcribe, /avo.pipeline

Read [organize guidance](../../agent-skills/avo-pipeline/references/organize.md) and follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md). Use the declared step names in the footer and read durable state again on resume.

## Usage

```text
/avo.organize
Provider: my-channel
rawDir: D:/Footage/library
```

The provider must already be configured. The absolute footage root must exist outside the AVO checkout. An unspecified action means native `scan` followed by visual review. Include subfolders only when the user explicitly selects recursive scope.

Clone runtime:

```powershell
python -m avo.cli organize scan --root 'D:\Footage\library' --provider my-channel --json
```

Installed engine: `avo organize scan --root <absolute-root> --provider <configured-provider> --json`. All organize operations require this root/provider context. Replace example paths and names with the user's actual declared values.

## Instructions

1. Resolve the provider, footage root and recursive scope. Do not initialize an editing pipeline merely to index files.
2. Run native `scan`. Default inventory/proposal work performs metadata probing without ASR, content watching, uploads or source moves. Outputs belong under the footage root's `edit/` area.
3. Present the returned HTML and text review links, current/proposed folder hierarchy, grouping evidence, uncertain assignments, exact original/destination paths, counts and conflicts. Explain metadata-only grouping without claiming knowledge of unseen footage. Browser edits export a request; they do not move files or approve work.
4. Run only the requested follow-up: import reviewed edits through `propose --request ... --request-sha256 ...`; search/select footage; prepare approved-source moves; or prepare an optional local transcription batch. Follow the reference for exact requests and gates.
5. For moves or a batch, first produce the concrete prepared packet, selected IDs, source evidence, resource/cost disclosures and blockers. Obtain the creator's explicit decision for that exact packet before recording `approve` and invoking `apply` or `batch run`. Never infer approval from a browser export, a previous proposal or an AI review.
6. Automatically report actual results and performance: processed/reused/failed counts, elapsed time against available estimates, created versus moved bytes, footprint/free disk and cost/token coverage. Unknowns remain unknown. Link the returned report, disclose incomplete work and offer the valid next action.

Physical moves require supported fixed local Windows NTFS storage. Existing project/NLE references, unknown ownership, occupied targets and closed roots block affected work. No overwrite, cross-volume copy/delete fallback, implicit reopening or automatic cleanup is permitted. `reverse` creates a new proposal; it requires its own review, preparation and approval.

Use `status`, `cancel` and `resume` with the returned operation ID. Cancellation stops new admissions; the current item may finish and must remain visible until settled. Paid transcription is unavailable. Local batches use one prepared local model on CPU/int8 with one worker and an explicit thread/time allowance.

## Shared timeline gateway

Search and selection retain original-source identities, current paths, source ranges and evidence. They do not generate BL-011 composition briefs, EDLs, edits, proofs or masters. Existing editorial and delivery approvals remain downstream requirements.
