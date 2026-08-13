# T072: Switch Batch Migration Runbook

Operator procedure to prove ten-Short parity using only `python -m avo.shorts`.

## Prerequisites

- [ ] Approved Switch master mounted locally
- [ ] Word transcript for that master
- [ ] Insertion source (Nier) with PCSHOP stream `0:a:0`
- [ ] Provider `bishop` with `brand/palette.json` on operator machine
- [ ] FFmpeg + HyperFrames CLI available
- [ ] Canonical request: [tests/fixtures/shorts/switch-comparison/shorts.request.json](../../tests/fixtures/shorts/switch-comparison/shorts.request.json) (paths updated to local mounts)

## Command sequence

Run from footage `edit/` directory. Replace paths as needed.

```bash
# 1. Validate + resolve
python -m avo.shorts validate shorts/switch-comparison/shorts.request.json
python -m avo.shorts resolve shorts/switch-comparison/shorts.request.json \
  -o plans/switch-comparison-shorts.plan-v001.json

# 2. Human plan approval (edit plan JSON, set planApproval + planHash)

# 3. Optional cheap preview
python -m avo.shorts build plans/switch-comparison-shorts.plan-v001.json \
  --stage proof --preview --workers 2

# 4. Full proofs
python -m avo.shorts build plans/switch-comparison-shorts.plan-v001.json \
  --stage proof --workers 2

# 5. QC
python -m avo.shorts qc plans/switch-comparison-shorts.plan-v001.json --stage proof

# 6. Watch LOOP on all proofs; insertion semantics on 02, 04, 06

# 7. Promote
python -m avo.shorts promote plans/switch-comparison-shorts.plan-v001.json \
  --approval-manifest review/switch-comparison-approvals.json \
  --delivery-dir delivery/switch-comparison
```

## Parity checklist

| Check | Expected |
|-------|----------|
| Count | 10 Shorts |
| Insertions | 02, 04, 06 only |
| Audio stream | `0:a:0` (PCSHOP) |
| Gameplay window | 5.0–46.5 s |
| Caption rails | Anchor-rail, phrase reset |
| Nier repeat at 00:42–00:43 | Safe finite repeat |
| Scripts used | None from `scripts/*switch*` or anchor-rail pilots |

## Evidence to record

Update [migration-evidence.json](../../tests/fixtures/shorts/switch-comparison/migration-evidence.json):

```json
{
  "version": "1.1",
  "recordedAt": "YYYY-MM-DD",
  "status": "complete",
  "planHash": "<64-char hex>",
  "proofRevisions": { "01": 1, "...": 1 },
  "qcSummary": { "passed": 10, "failed": 0 },
  "watchApprovals": {
    "batch": "watch://...",
    "insertions": { "02": "...", "04": "...", "06": "..." }
  },
  "completed": {
    "fullRealBatchRenderedOnlyThroughAvoShorts": true,
    "watchVisualParityApprovalForTenNewProofs": true
  },
  "pending": {
    "scriptRetirement": true
  },
  "removalDecision": "awaiting explicit user approval for T075-T076"
}
```

Set `pending.scriptRetirement` to `false` only after user approves script deletion.

## Exit criteria

- All ten proofs and masters produced exclusively via CLI above
- QC passed at full resolution for all items
- Watch approval recorded
- `migration-evidence.json` updated
- No one-off scripts invoked during the run

## Blocked follow-ups

- **T075–T076**: Delete one-off scripts only after this runbook completes + user sign-off
- **T080**: CHANGELOG after user confirms 100% working
