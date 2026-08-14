# Quickstart: Batch Shorts Workflow

Operator flow from one approved master to immutable delivery.

## Prerequisites

- Approved master MP4 + word-timed transcript JSON
- `shorts.request.json` with candidates, policies, optional insertions
- Provider palette at `providers/<provider>/brand/palette.json`
- FFmpeg, Python 3.10+, HyperFrames CLI

## Steps

### 1. Validate and resolve

```bash
python -m avo.shorts validate /path/to/shorts.request.json
python -m avo.shorts resolve /path/to/shorts.request.json \
  -o /path/to/edit/plans/shorts.plan-v001.json
```

### 2. Approve plan

Edit the plan JSON in place (immutable revision):

```json
"planApproval": {
  "status": "approved",
  "reference": "human-review:batch-plan-20260813",
  "timestamp": "2026-08-13T12:00:00Z"
}
```

Recompute `planHash` via resolve or tooling that calls `shorts_contract.plan_hash`.

### 3. Optional preview proofs

```bash
python -m avo.shorts build /path/to/shorts.plan-v001.json --stage proof --preview --workers 2
```

Review 640×360 proofs. Full build auto-dirties items via `renderProfile`.

### 4. Full proofs

```bash
python -m avo.shorts build /path/to/shorts.plan-v001.json --stage proof --workers 2
python -m avo.shorts qc /path/to/shorts.plan-v001.json --stage proof
python -m avo.shorts status /path/to/shorts.plan-v001.json
```

### 5. Watch review

Record Watch references for insertion-bearing Shorts in approval manifest `watchReviews`.

### 6. Promote

```bash
python -m avo.shorts promote /path/to/shorts.plan-v001.json \
  --approval-manifest /path/to/approvals.json \
  --delivery-dir /path/to/edit/delivery/<batchId>
```

`approvals.json` must include gates: `batch-plan`, `motion-proof`, `picture-lock`, `rights`, `pre-master`.

## Selective rebuild

```bash
python -m avo.shorts build /path/to/plan.json --stage proof --short 04
python -m avo.shorts qc /path/to/plan.json --stage proof --short 04
```

## Recovery

- Failed items stay `failed` + `dirty`; siblings unchanged.
- Shared policy change → new plan revision → affected fingerprints dirty.
- Preview → full: automatic `render-profile-changed` dirty reason.
