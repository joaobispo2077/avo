# Quickstart Validation: Generic Guided AVO Workflows

This guide is for validating the implementation after `/speckit.tasks` and `/speckit.implement`. It does not migrate real footage automatically.

## Prerequisites

- Python 3.10+ environment installed through the repository's normal `uv` workflow.
- FFmpeg/FFprobe available for media integration cases.
- Watch Skill installed only for live adapter smoke tests; pure policy/adapter tests use fakes.
- A disposable footage-project directory for CLI scenarios.

## 1. Fast contract suite

```powershell
uv run --frozen --extra dev pytest -q `
  tests/test_avo_commands.py `
  tests/test_avo_step_status_contract.py `
  tests/test_shorts_paths.py `
  tests/test_shorts_contract.py `
  tests/test_shorts_plan.py `
  tests/test_watch_policy.py `
  tests/test_watch_adapter.py `
  tests/test_source_fidelity_qc.py
```

Expected: every AVO wrapper declares workflow guidance; v1.0 and v1.1 Shorts contracts pass; path/policy/fidelity invalid inputs fail before media work.

## 2. Canonical Shorts root

Resolve a v1.1 request into a disposable footage project:

```powershell
uv run --frozen python -m avo.shorts resolve .\tests\fixtures\shorts\planning-v11\shorts.request.json `
  --raw-dir D:\avo-fixtures\video-001
```

Expected artifacts:

```text
D:/avo-fixtures/video-001/edit/shorts/
  shorts.index.json
  <batchId>/
    shorts.request-v001.json
    plans/shorts.plan-v001.json
    plans/shorts.status.json
```

The plan reports `batchRoot`, `batchRootSource`, and ordered `sourceSegments`. A split `--delivery-dir` on that v1.1 plan fails with guidance to use the canonical batch root.

## 3. Ordered segment behavior

Use the v1.1 fixture whose source order is `10–12`, then `30–32`, then
`20–22`.

```powershell
uv run --frozen --extra dev pytest -q tests/test_shorts_plan.py -k segment_order
uv run --frozen --extra dev pytest -q tests/test_shorts_captions.py -k segment
uv run --frozen --extra dev pytest -q tests/test_shorts_media.py -k segment
```

Expected:

- output order remains `10–12`, then `30–32`, then `20–22`;
- edited duration is the sum after speed;
- hashes change when order changes;
- captions use cumulative output offsets and cannot bridge a seam;
- no plan, manifest, or log synthesizes one enclosing source range.

Then validate the legacy fixture:

```powershell
uv run --frozen --extra dev pytest -q tests/test_shorts_contract.py -k v10_compatibility
uv run --frozen --extra dev pytest -q tests/test_shorts_plan.py -k exact_count_order_duration
uv run --frozen --extra dev pytest -q tests/test_shorts_paths.py -k legacy_inference
```

Expected: existing v1.0 input produces the same meaning through a one-segment in-memory normalization and the original file is not rewritten.

## 4. Inspect Watch policy without running Watch

```powershell
uv run --frozen python -m avo.cli review policy `
  --project D:\avo-fixtures\video-001\avo.project.json `
  --watch-device cpu `
  --watch-whisper-model inherit `
  --watch-format explainer `
  --watch-language en `
  --watch-acceptance-criterion "No unreadable on-screen text"
```

Expected JSON includes effective values, the winning source for each field, and `policyHash`. It performs no indexing. Removing format/language omits them from generated prompt context; it does not inject a topic or language. Only explicit CPU policy sets the CPU environment override.

## 5. Watch fail-closed cases

```powershell
uv run --frozen --extra dev pytest -q tests/test_watch_adapter.py -k "refusal or malformed or coverage or echoed"
uv run --frozen --extra dev pytest -q tests/test_review_runner.py -k "policy_context or unrelated_policy"
```

Expected: the parser chooses the last schema-valid analysis object; recognized refusal/uncertainty remains human judgment; exhausted malformed/tool output blocks; missing required-window coverage blocks; raw attempts and policy fingerprint remain in evidence.

## 6. Delivery fidelity from canonical materialization

```powershell
uv run --frozen --extra dev pytest -q tests/test_source_fidelity_qc.py
uv run --frozen --extra dev pytest -q tests/test_review_runner.py -k "fidelity or materialization"
uv run --frozen --extra dev pytest -q `
  tests/test_timeline_materialize.py `
  tests/integration/test_master_delivery_review.py
```

Expected scenarios:

- native or declared scale-down delivery passes;
- declared landscape-to-portrait reframe passes;
- undeclared reframe fails;
- proof/proxy used as base fails and names the node;
- permitted lower-resolution overlay follows its role policy;
- bitrate constraints apply only to the declared codec;
- stale locks, changed policy, missing lineage, or candidate hash mismatch block.

A live pre-master review uses the materialization, not ad hoc lineage:

```powershell
uv run --frozen python -m avo.cli review run `
  --project D:\avo-fixtures\video-001\avo.project.json `
  --checkpoint pre-master `
  --materialization D:\avo-fixtures\video-001\edit\timeline\materializations\assembly\assembly-001.json
```

Expected: review dependencies include canonical revision, materialization, lineage, output, and fidelity-policy hashes.

## 7. Reconstruction and cleanup preservation

```powershell
uv run --frozen --extra dev pytest -q `
  tests/test_reconstruction_bundle.py `
  tests/test_shorts_delivery.py `
  tests/test_shorts_batch_integration.py
```

Expected: request snapshots, plans, status, approvals, delivery masters, final-file transcript sidecars, manifests, `EDITLOG.md`, and `SOURCE-LOG.md` are preserved. Documented `work/` artifacts remain cleanup candidates.

## 8. Full repository gates

```powershell
uv run --frozen --extra dev pytest -m "not project" --ignore=tests/projects
npm run test:unit
npm run quality
```

Expected: all core tests and software-quality gates pass. Run `npm run test:projects` separately for footage-project regression fixtures.

## Acceptance summary

The feature is ready only when all four runtime contracts and the prompt contract pass together: canonical paths are preserved, ordered lineage is reconstructable, Watch is generic/configurable/fail-closed, delivery fidelity is lineage/profile-driven, and every AVO response ends with verified current/next guidance.
