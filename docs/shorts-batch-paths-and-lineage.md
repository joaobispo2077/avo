# Shorts batch paths and ordered lineage

AVO owns every Shorts batch beneath one footage-project root. This keeps the
request, plan, approvals, work files, delivered masters, transcripts, and logs
discoverable by one stable `batchId` without embedding a provider or video path
in generic code.

## Canonical tree

```text
<rawDir>/edit/shorts/
├── shorts.index.json
└── <batchId>/
    ├── shorts.request-v001.json
    ├── approvals/
    ├── plans/
    │   ├── shorts.plan-v001.json
    │   └── shorts.status.json
    ├── work/
    └── delivery/
        ├── masters/
        ├── transcripts/
        ├── delivery-manifest.json
        ├── EDITLOG.md
        └── SOURCE-LOG.md
```

`--raw-dir` selects the footage project. `--batch-dir` is an optional nested
override under `<rawDir>/edit/shorts`; its final directory name must equal the
request `batchId`. Traversal, split roots, mismatched IDs, and v1.1 plans outside
`plans/` fail before media work. The atomic index rejects an existing `batchId`
registered to another root.

Use invocation flags for a one-run location. Persist `batchRoot` and
`batchRootSource` in v1.1 requests/plans so later stages reproduce the same
decision. Relative source and insertion paths are normalized before an external
request is snapshotted into the batch.

## Commands

```text
python -m avo.shorts validate incoming/shorts.request.json --raw-dir footage
python -m avo.shorts resolve incoming/shorts.request.json --raw-dir footage
python -m avo.shorts build footage/edit/shorts/demo/plans/shorts.plan-v001.json --stage proof --raw-dir footage
python -m avo.shorts qc footage/edit/shorts/demo/plans/shorts.plan-v001.json --stage proof --raw-dir footage
python -m avo.shorts status footage/edit/shorts/demo/plans/shorts.plan-v001.json --raw-dir footage
python -m avo.shorts promote footage/edit/shorts/demo/plans/shorts.plan-v001.json --approval-manifest approvals.json --raw-dir footage
```

For a campaign grouping, add `--batch-dir campaign/demo` consistently. The
resolver records the effective root; later stages reject a conflicting one.

## Ordered source segments

Request v1.1 replaces each candidate `sourceRange` with a non-empty
`sourceSegments` array. Array position is authoritative and `order` must match
that position; AVO never sorts segments by source time. Every segment records
source identity, source interval, rationale, evidence reference, and optional
overlap approval. Zero duration, out-of-bounds ranges, unapproved overlap, and a
changed source fingerprint fail closed.

Planning maps each segment cumulatively onto output time. Caption corrections
are applied in source time, phrases stop at seams, output IDs are globally
reindexed, and picture/dialogue are concatenated in declared order with 30 ms
audio seam protection. Each proof writes `prepared-lineage.json`; its hash is
part of the composition, and all joins become required Watch windows.

The neutral contract fixture demonstrates a deliberately non-chronological
three-part assembly: `10–12`, then `30–32`, then `20–22`. Neither the plan nor
delivery records replace these segments with an enclosing range.

Delivery records retain ordered base and insertion lineage, preparation hashes,
Watch and human approvals, rights/factual references, disclosure and
privacy/safety notes, AI-use/delivery metadata, and transcript sidecars produced
from the exact delivered files. `SOURCE-LOG.md` and `EDITLOG.md` summarize the
same machine-readable manifest rather than replacing it.

## Preservation and compatibility

Cleanup preserves the batch index, request snapshots, plans, status, approval
snapshots, and the entire delivery tree. Documented scratch beneath `work/` may
be removed after immutable delivery evidence exists.

v1.0 single-range requests remain readable for the 1.x schema line and are
normalized to one in-memory segment. `--delivery-dir` is deprecated and accepted
only for v1.0; AVO records `legacyExternalDelivery` and prints migration
guidance. v1.1 rejects split delivery and requires `--raw-dir` plus the canonical
root. No existing files are moved automatically.

## Failure and next action

Path or contract errors stop before rendering. Correct `rawDir`, `batchId`, or
the declared segment evidence and rerun the same stage. After `resolve`, review
and approve the immutable plan. After proof QC, run Watch and the required human
gates. After promotion, verify the delivery manifest and proceed to delivery QC.

## Current-source audit

Accessed 2026-09-02: YouTube's official
[aspect-ratio guidance](https://support.google.com/youtube/answer/6375112?co=GENIE.Platform%3DDesktop&hl=en)
states that the player adapts to vertical video and recommends avoiding embedded
padding. This supports validating the selected vertical profile; it does not
justify hardcoding one batch path, duration, bitrate, or creative treatment in
AVO.
