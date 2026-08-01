# Footage-project tests (not AVO core)

These modules validate **specific video edits** tied to `specs/00N-*` feature folders
(for example switch-comparison, bluray-ps5-gamevlog). They are **not** part of the
orchestrator quality gate.

| Module | Spec / project |
| --- | --- |
| `test_switch_comparison_edl_contract.py` | `003-switch-comparison-video` |
| `test_switch_comparison_motion_briefs.py` | `003-switch-comparison-video` |
| `test_final_transcript_artifacts.py` | switch-comparison export naming |
| `test_bluray_ps5_edl_contract.py` | `005-bluray-ps5-gamevlog` |
| `test_bluray_ps5_render_schema.py` | `005-bluray-ps5-gamevlog` |

**Default CI / PR:** `bash scripts/ci/run-unit-tests.sh` runs `pytest -m "not project"`.

**Run project tests locally:**

```bash
pytest tests/projects
# or
npm run test:projects
```

Provider-specific configs (e.g. `providers/bishop/`) are gitignored and are **never**
required for AVO core tests.
