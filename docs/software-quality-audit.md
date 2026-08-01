# AVO Software Quality Audit

**Task:** `avo-refactoring-software-quality` · **Date:** 2026-08-01

Agent- and maintainer-facing map of **what is tested**, **what is gated**, and **where
instructions live**. See also [software-foundation.md](./software-foundation.md) and
[ci.md](./ci.md).

---

## Audiences

| Audience | Primary entry | Quality expectation |
| --- | --- | --- |
| **AI agents** | `AGENTS.md`, `.cursor/rules/`, Copilot instructions | pytest + Gate 1/2 before claiming setup works |
| **Maintainers** | `docs/ci.md`, `docs/launch.md`, this doc | Full pytest in CI; release tag alignment |
| **Human editors** | `docs/avo-workflow.md`, footage `edit/` QC | Editorial gates + engine contract tests |

---

## Validation gates

| Gate | Script | Validates |
| --- | --- | --- |
| **Gate 1** | `scripts/validate-prerequisites.sh --ci` | Spec Kit, engine, ffmpeg, watch-skill, HyperFrames, optional clones |
| **Gate 2** | `scripts/validate-usability.sh --ci` | `avo.config.json`, provider scaffold, setup dry-run, core helpers |

**CI order:** Gate 1 → pytest **AVO core** (`-m "not project"`) → install smoke + hf:doctor → Gate 2.

**Release order:** Gate 1 → Gate 2 → pytest (AVO core) → version check → GitHub Release.

---

## Test runner

| Command | Purpose |
| --- | --- |
| `pip install -e ".[dev]"` | Install pytest + dev deps |
| `npm run test:unit` | **AVO core** — `pytest -m "not project"` |
| `npm run test:projects` | Footage-project / spec-scoped tests only |
| `pytest` | Everything (core + projects) |
| `bash scripts/ci/run-unit-tests.sh` | Canonical CI entry (core only) |

**Enforcement:** `tests/test_quality_matrix.py` fails if workflows or docs drift.

Provider instances (e.g. `providers/bishop/`) are **gitignored** and never required for core tests.

---

## Test matrix

### Tier A — Orchestrator (always in PR CI)

| Test module | Covers |
| --- | --- |
| `test_avo_config` | `avo.config.json`, validate helper smoke |
| `test_avo_commands` | Command parity |
| `test_install_scripts` | Install slug `joaobispo2077/avo` |
| `test_validate_dependencies` | Gate 1 manifest |
| `test_local_only_customization` | Local-only paths |
| `test_workflow_compatibility` | Workflow contracts |
| `test_gitignore_scope` | Provider gitignore |
| `test_video_use_traces` | Product identity |
| `test_software_foundation` | Foundation file layout |
| `test_quality_matrix` | Doc/workflow drift guard |
| `test_init_project` | `helpers/init_project.py` scaffold |

### Tier B — Engine core (AVO core pytest, PR CI)

| Test module | Covers |
| --- | --- |
| `test_transcribe` | `helpers/transcribe.py` (mocked Whisper) |
| `test_transcribe_batch` | Batch transcribe |
| `test_transcribe_cache` | Cache invalidation |
| `test_prepare_transcription` | Model prep (mocked download) |
| `test_transcript_contract` | Transcript schema |
| `test_edl_v3_contract` | EDL v3 + `validate_edl.py` |
| `test_caption_plan` | Caption planning |
| `test_render_schema_selection` | Render schema (generic) |
| `test_overlay_composite` | Overlay composite |
| `test_audio_sfx_pipeline` | Audio SFX pipeline |

### Tier C — Footage projects (local only, **not** PR CI)

Under `tests/projects/` — `@pytest.mark.project`. Spec-scoped edits only.
Run: `npm run test:projects`.

| Test module | Spec / project |
| --- | --- |
| `projects/test_switch_comparison_edl_contract.py` | `003-switch-comparison-video` |
| `projects/test_switch_comparison_motion_briefs.py` | `003-switch-comparison-video` |
| `projects/test_final_transcript_artifacts.py` | switch-comparison exports |
| `projects/test_bluray_ps5_edl_contract.py` | `005-bluray-ps5-gamevlog` |
| `projects/test_bluray_ps5_render_schema.py` | `005-bluray-ps5-gamevlog` |

### Tier D — Slow / manual workflows

| Workflow | Extra checks |
| --- | --- |
| `orchestrator-smoke.yml` | Whisper tiny model, optional tools, AVO core pytest |
| `setup-smoke.yml` | Full setup ubuntu/windows |
| `ffmpeg-whisper-smoke.yml` | Binary import smoke |

---

## Workflow trigger matrix

| Workflow | Trigger | Tests |
| --- | --- | --- |
| `ci.yml` | PR + push main/dev/feature | AVO core pytest (`-m "not project"`) |
| `release.yml` | `v*` tags | AVO core pytest + version check + GitHub Release |
| `orchestrator-smoke.yml` | weekly + manual | AVO core pytest + model prep |
| `setup-smoke.yml` | manual | Setup scripts |
| `ffmpeg-whisper-smoke.yml` | manual | ffmpeg/whisper imports |

---

## Known gaps (deferred)

| Helper | Status |
| --- | --- |
| `helpers/grade.py` | No dedicated unit test — manual QC |
| `helpers/telemetry.py` | No dedicated unit test |
| `helpers/hardware.py` | No dedicated unit test |
| `helpers/validate_edl.py` CLI | Covered indirectly via EDL contract tests |

---

## Local quality checklist

```bash
pip install -e ".[dev]"
npm ci
bash scripts/validate-prerequisites.sh --ci
bash scripts/ci/run-unit-tests.sh          # AVO core only
bash scripts/validate-usability.sh --ci
npm run test:unit

# Optional — footage-project tests (not gated in CI):
npm run test:projects
```

Pre-tag (maintainer):

```bash
bash scripts/ci/verify-release-version.sh v0.1.0   # after CHANGELOG section exists
```

---

*Maintained as part of the software quality refactor.*
