# Contract: Canonical Shorts Batch and Ordered Lineage

## Canonical layout

```text
<rawDir>/edit/shorts/<batchId>/
├── shorts.request-vNNN.json
├── plans/
│   ├── shorts.plan-vNNN.json
│   └── shorts.status.json
├── approvals/
│   └── approval-vNNN.json
├── work/
│   └── <shortId>/proof-vNNN/{prepared,hyperframes,renders,qc}/
└── delivery/
    ├── masters/
    ├── transcripts/
    ├── delivery-manifest.json
    ├── EDITLOG.md
    └── SOURCE-LOG.md
```

`<rawDir>/edit/shorts/shorts.index.json` records every canonical or supported nested batch root by immutable batch ID and plan hash.

Requests, plans, status, approvals, and delivery are preservation roots. `work/` is scratch and may be cleaned after current immutable review/delivery references are retained.

## Resolver inputs and rules

The resolver accepts `rawDir`, `batchId`, an optional validated `batchDir`, and, for compatibility only, a plan path. Default `batchRoot` is `<rawDir>/edit/shorts/<batchId>`.

- `batchRoot` is normalized once with `pathlib`.
- It must remain within `<rawDir>/edit/shorts/` and have basename `batchId`. A supported override may be nested (for example `shorts/campaign-2026/<batchId>`).
- A new request authored elsewhere is snapshotted into the batch root before plan creation.
- A v1.1 plan must live under `<batchRoot>/plans/` and persists `batchRoot` plus `batchRootSource`.
- Every later stage verifies `batchId`, plan hash, recorded root, and physical plan location.
- Resolution updates the project-owned Shorts index atomically; reconstruction/cleanup enumerate that index and validate each recorded root before use.
- Default delivery is always `<batchRoot>/delivery`.
- `--delivery-dir` is deprecated. v1.1 accepts it only when it equals the canonical delivery directory. v1.0 may use an explicit legacy location for one compatibility window and records `legacyExternalDelivery: true` plus a warning.

Public resolution controls:

- `--raw-dir PATH`: supplies the footage-project root when request location cannot prove it.
- `--batch-dir PATH`: invocation-only supported override inside `<rawDir>/edit/shorts/`; persisted as the effective root.
- Existing `-o`: remains accepted when its path agrees with the resolved `plansDir`; legacy v1.0 layout inference remains read-only.

## Request v1.1

Version 1.1 keeps one primary media source but gives it stable identity:

```json
{
  "version": "1.1",
  "batchId": "launch-clips-001",
  "source": {
    "sourceId": "master",
    "masterPath": "D:/footage/edit/delivery/master.mp4",
    "transcriptPath": "D:/footage/edit/transcripts/master.json",
    "expectedFingerprint": "<sha256>"
  },
  "candidates": [
    {
      "id": "01",
      "order": 1,
      "coreIdea": "One truthful idea",
      "viewerPromise": "One viewer payoff",
      "postingTitle": "Example",
      "sourceEvidence": "ordered transcript evidence",
      "sourceSegments": [
        {
          "order": 1,
          "sourceId": "master",
          "startSec": 30.0,
          "endSec": 35.0,
          "rationale": "Establish the claim",
          "evidenceReference": "review://01/segment-1"
        },
        {
          "order": 2,
          "sourceId": "master",
          "startSec": 20.0,
          "endSec": 24.0,
          "rationale": "Deliver the earlier proof second",
          "evidenceReference": "review://01/segment-2"
        }
      ],
      "editorialApprovalReference": "review://01"
    }
  ]
}
```

All current unrelated required fields remain required. Version 1.1 requires `sourceSegments` and forbids `sourceRange`. Array position is authoritative and `order` must match it. Finite positive ranges, source identity, source duration, transcript evidence, and overlap approvals are validated before plan creation. Reordered segments are valid and never auto-sorted.

## Resolved plan v1.1

New resolver output always uses v1.1 and includes:

```json
{
  "version": "1.1",
  "batchRoot": "D:/footage/edit/shorts/launch-clips-001",
  "batchRootSource": "canonical-default",
  "sourceFingerprint": "<sha256>",
  "items": [
    {
      "id": "01",
      "speed": 1.0,
      "sourceSegments": [
        {
          "segmentId": "01-s001",
          "order": 1,
          "sourceId": "master",
          "sourceFingerprint": "<sha256>",
          "startSec": 30.0,
          "endSec": 35.0,
          "outputStartSec": 0.0,
          "outputEndSec": 5.0,
          "rationale": "Establish the claim",
          "evidenceReference": "review://01/segment-1"
        }
      ],
      "lineageOrigin": "declared-sourceSegments"
    }
  ]
}
```

`editedDurationSec` is the sum of segment durations divided by candidate speed. Duplicate and input fingerprints include the complete ordered segment tuple. Plans never emit a synthetic enclosing range.

## Assembly and captions

- Re-hash the source and compare with plan lineage before preparation.
- Extract/assemble picture and dialogue in declared order using one deterministic graph or equivalent lossless deterministic join that preserves the current 30 ms seam protection.
- Write `prepared-lineage.json` with plan, source, segment, join-window, and prepared-asset hashes.
- Apply transcript corrections in source time per segment, map words using cumulative output offsets, force phrase boundaries at every segment seam, then assign globally unique phrase/word IDs.
- Watch required windows include every segment join.

## Delivery records

Each item in the machine-readable manifest and `SOURCE-LOG.md` preserves ordered base segments, source/prepared hashes, source/output windows, rationale, evidence reference, insertion time maps and rights basis, approval-manifest hash, proof/master identities, and final transcript sidecars. `EDITLOG.md` records assembly order, speed, and declared transformations. No record substitutes an enclosing `sourceRange`.

## Compatibility

- v1.0 request: current `sourceRange` schema remains valid.
- v1.0 normalization: one segment, `sourceId=source.sourceId || master`, `rationale=coreIdea`, `evidenceReference=editorialApprovalReference`, `lineageOrigin=legacy-sourceRange-v1.0`.
- Existing v1.0 plans remain readable/buildable through an in-memory view and are never rewritten automatically.
- Existing v1.0 fixtures stay as regression coverage; new fixtures exercise v1.1 reorder, overlap, boundary, and hashing behavior.
