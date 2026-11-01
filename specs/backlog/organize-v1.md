# BL-010 — `/avo.organize` v1

**Status:** Implementation delivered; acceptance pending

**Slash surface:** `/avo.organize`

## Summary

Index a declared external footage root and show a navigable current/proposed folder structure with exact file mappings, reasons, uncertainty and conflicts. Root-level discovery remains the default, with explicitly selected nested scope. Review exports changes for native import; it cannot approve or move files.

Native source-bound preparation and explicit creator approval permit selected no-overwrite moves on tested fixed local Windows NTFS. Metadata/speech search and bounded source handoffs reuse indexed evidence. Optional local CPU/int8 transcription freezes model, language, one-worker CPU/time limits and reuse evidence. Paid routes are unavailable. Progress and outcome reports preserve unknown cost/token coverage.

This implementation supersedes the original flat-only FR-B1 baseline and its assumption of whole-directory transcript packing. BL-011 composition briefs, EDL generation, rendering, automatic deletion and implicit cleanup are outside this feature.

## Acceptance status

Implemented safety, recovery, search, local batch, offline review and compatibility behavior is covered by the library test suites. Reference-scale performance now passes, including search during actual local transcription and unchanged refresh of 1,000 playable recordings. The user-requested five-person comprehension study remains pending, and an existing locked dependency advisory blocks the full repository quality gate. This is not a full acceptance or release claim; no participant outcomes or universal speed guarantees are inferred from automated tests.

See the [public capability and limitation guide](../../docs/library-organize.md) and [portable command reference](../../agent-skills/avo-pipeline/references/organize.md).

## Spec

Current local specification: [`013-library-organize/spec.md`](../013-library-organize/spec.md). Historical scope: [`avo-capabilities-roadmap/spec.md`](../active/avo-capabilities-roadmap/spec.md), FR-B1.
