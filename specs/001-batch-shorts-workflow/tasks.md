# Tasks: Batch Shorts Workflow

**Input**: Design documents from `/specs/001-batch-shorts-workflow/`

## Phase 8: Audit Resolution (2026-08-13)

- [X] T081–T087 Provider tokens, QC depth, contact sheets, schema refinements, preview CLI, status/QC summary, audit-resolutions.md

## Phase 9: Closure (2026-08-13)

- [X] T088 Persist `renderProfile` on proof builds and invalidate dirty items when preview/full target changes (`shorts.py`, `shorts_plan.py`, status schema)
- [X] T089 Add Phase 9 tests: provider, QC CLI, promote CLI, preview→full rebuild, selectionRule, QC metrics
- [X] T090 Refresh spec/plan to v1.2, add quickstart + T072 runbook, update audit-resolutions
- [X] T091 Make `promote_batch` transcript generator patchable at call time (`shorts_delivery.py`)
- [ ] T072 Run real Switch batch only through `/avo.shorts`; capture Watch approval in `migration-evidence.json` — **operator-gated**
- [ ] T075–T076 Script retirement — **blocked on T072 + explicit user approval**
- [ ] T078 Full validation record — **partial** (see below; `test:projects` still operator-gated)
- [ ] T079 Constitution recheck after T072 — see [t079-constitution-recheck.md](t079-constitution-recheck.md)
- [ ] T080 CHANGELOG — **blocked on user 100% approval**

## Prior phases

Phases 1–7 (T001–T074) complete except T072/T075–T080 above.

## Validation record (T078)

Commands run 2026-08-13 on Windows (Python 3.11, `PYTHONPATH=src`):

```text
python -m unittest tests.test_shorts_captions tests.test_shorts_media tests.test_shorts_qc \
  tests.test_shorts_plan tests.test_shorts_contract tests.test_shorts_provider \
  tests.test_shorts_batch_integration tests.test_shorts_delivery -q
# Ran 49 tests — OK

python -m unittest discover -s tests -p "test_*.py"
# Ran 344 tests — OK (after Windows hyperframes .bin shim fix)

python -m pytest tests/ -m "not project" --ignore=tests/projects -q
# 344 passed
```

Pending (operator / mounted footage):

```bash
npm run test:unit          # needs working .venv or pytest on PATH
npm run test:projects      # requires mounted Switch transcript
```
