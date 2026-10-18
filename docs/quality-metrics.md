# Quality metrics

Release readout of the exact commit and CI run. Measurements and thresholds do not replace mandatory checks.

| Field | Value |
|---|---|
| Version | 1.16.0 |
| Tag | v1.16.0 |
| SHA | `204b08f392a5b826a88a0ac5ced8d9880232b92d` |
| Recorded (UTC) | 2026-10-18T01:05:20Z |

## AVO quality

**Overall: PASS**

Commit: `204b08f392a5b826a88a0ac5ced8d9880232b92d` · Run: `39084599780`

PR head: `Unavailable`
PR base: `Unavailable`
Tested revision: `204b08f392a5b826a88a0ac5ced8d9880232b92d`
Attempt: 1. Passed producer evidence may come from earlier attempts of the same run.

All mandatory gate decisions and required jobs passed.

![Quality dashboard](quality/charts/1.16.0/dashboard.png)

**Measurements**

Evidence completeness: 9 measured, 1 partial, 1 unavailable. Gate decisions are below.

Unavailable evidence: Safety branch coverage.

| Metric | Measured | Scope | Evidence |
|---|---|---|---|
| Line coverage | 71.42% | unit suite; src/avo | 18,421/25,794 executable lines [coverage.json](https://github.com/joaobispo2077/avo/actions/runs/39084599780/artifacts/12119714109) (SHA-256 `e4b673f81ec8`) |
| Duplication | 0.77% | source lines; src/avo | 440/56,949 duplicated lines; 41 clone pairs [jscpd/jscpd-report.json](https://github.com/joaobispo2077/avo/actions/runs/39084599780/artifacts/12119714109) (SHA-256 `43a7103dfb97`) |
| Mutation efficacy | 64.89% | light profile; selected Python modules | 207 killed / 112 survived / 319 total; 0 unresolved [mutation-metrics.json](https://github.com/joaobispo2077/avo/actions/runs/39084599780/artifacts/12120675814) (SHA-256 `ff8ab4bd0fcc`) |

### Mutation efficacy by source

PARTIAL: Scope counters reconcile; some efficacy measurements are unavailable.
Existing mutation enforcement applies to the aggregate profile. Source colors and the aggregate floor line are informational comparisons.

![Mutation efficacy and outcome accounting](kpi-chart:mutation-efficacy.png)

Aggregate: 207 killed / 112 survived / 319 total; 0 unresolved. Complete execution: True.

Source excerpt: 5/5. Missing/incomplete first, then lowest measured efficacy; M IDs sort by full source path.

| Source ID and full path | Efficacy / state | Actual outcome counts |
|---|---|---|
| M005: [src/avo/validate_usability.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/validate_usability.py) | Zero mutants; efficacy unavailable. | 0 killed / 0 survived / 0 total; 0 unresolved |
| M004: [src/avo/validate_dependencies.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/validate_dependencies.py) | 52.13% | 110 killed / 101 survived / 211 total; 0 unresolved |
| M002: [src/avo/mcp/bridge.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/mcp/bridge.py) | 87.18% | 68 killed / 10 survived / 78 total; 0 unresolved |
| M003: [src/avo/mcp/registry.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/mcp/registry.py) | 95.65% | 22 killed / 1 survived / 23 total; 0 unresolved |
| M001: [src/avo/adapters/registry.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/adapters/registry.py) | 100.00% | 7 killed / 0 survived / 7 total; 0 unresolved |

[Complete mutation source index and outcome proof (text archive)](kpi-detail:mutation-efficacy.md)


### Complexity and CRAP review

2277 observed functions; 2227 measured CRAP; 50 observed functions unmeasured; 0 source-analysis errors. Total population known.
CRAP reference 30 is informational. Existing complexity policy and exceptions remain separate.

![Complexity and CRAP hotspots](kpi-chart:hotspots.png)

**Cyclomatic complexity: 10/2277 eligible candidates shown**. highest observed values, capped at 10; ties: descending value, then canonical path, definition line, qualified name.

| ID | Full source identity | Observed value | Unit |
|---|---|---:|---|
| U0009 | [src/avo/adapters/media/audio_tracks.py:61 compile_continuous_audio_graph](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/adapters/media/audio_tracks.py#L61) | 51 | independent paths |
| U2182 | [src/avo/validate_edl.py:110 _bluray_ps5_semantic_errors](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/validate_edl.py#L110) | 49 | independent paths |
| U0761 | [src/avo/learndown_export.py:87 build_timeline_learning_snapshot](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/learndown_export.py#L87) | 44 | independent paths |
| U1859 | [src/avo/timeline/proof_plan.py:407 ProofPlanCompiler.preflight](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/timeline/proof_plan.py#L407) | 43 | independent paths |
| U2066 | [src/avo/timeline/vision_review.py:194 compile_review_coverage](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/timeline/vision_review.py#L194) | 43 | independent paths |
| U2187 | [src/avo/validate_edl.py:289 _comparison_semantic_errors](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/validate_edl.py#L289) | 42 | independent paths |
| U1373 | [src/avo/timeline/approval_service.py:263 ApprovalService.decide](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/timeline/approval_service.py#L263) | 41 | independent paths |
| U2147 | [src/avo/update.py:282 run_update](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/update.py#L282) | 40 | independent paths |
| U0588 | [src/avo/cli.py:1030 _review_batch](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/cli.py#L1030) | 38 | independent paths |
| U1616 | [src/avo/timeline/iterations.py:255 IterationLedgerService.record_iteration](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/timeline/iterations.py#L255) | 38 | independent paths |

**CRAP: 10/2227 eligible candidates shown**. highest observed values, capped at 10; ties: descending value, then canonical path, definition line, qualified name.

| ID | Full source identity | Observed value | Unit |
|---|---|---:|---|
| U2182 | [src/avo/validate_edl.py:110 _bluray_ps5_semantic_errors](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/validate_edl.py#L110) | 2450 | CRAP score |
| U2187 | [src/avo/validate_edl.py:289 _comparison_semantic_errors](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/validate_edl.py#L289) | 1806 | CRAP score |
| U0588 | [src/avo/cli.py:1030 _review_batch](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/cli.py#L1030) | 1482 | CRAP score |
| U0335 | [src/avo/adapters/understand/watch_skill.py:1125 _native_review](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/adapters/understand/watch_skill.py#L1125) | 870 | CRAP score |
| U1796 | [src/avo/timeline/pipeline.py:572 TimelinePipeline.advance](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/timeline/pipeline.py#L572) | 735.738 | CRAP score |
| U0182 | [src/avo/adapters/qc/cut_proof.py:80 CutProofQcAdapter.check](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/adapters/qc/cut_proof.py#L80) | 702 | CRAP score |
| U1067 | [src/avo/render.py:1259 main](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/render.py#L1259) | 663.228 | CRAP score |
| U0318 | [src/avo/adapters/understand/watch_skill.py:717 execute_bounded_passes](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/adapters/understand/watch_skill.py#L717) | 600 | CRAP score |
| U0362 | [src/avo/audio_analysis.py:320 main](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/audio_analysis.py#L320) | 600 | CRAP score |
| U1994 | [src/avo/timeline/stills.py:182 StillExtractionService.extract](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/timeline/stills.py#L182) | 552 | CRAP score |


[Complete function index: hotspots.md (text archive)](kpi-detail:hotspots.md)


### File coupling: CE / CA

176 actual files at 62 positions; 483 distinct internal module edges; 0 namespace containers excluded from file points.
CE is horizontal (uses others); CA is vertical (used by others). Median references: CE 2, CA 1; all measured actual files including isolates, equality on the lower side. Spacing: piecewise log2(1 + count) around raw median; ticks show raw counts. Equal-area halves use independent scales around each median; equal areas do not mean equal numeric ranges. Regions describe connectivity, not architectural health or gate status.

![Indexed file coupling](kpi-chart:coupling-files.png)

Lookup excerpt: 20/62 coordinate groups; 78/176 files. Groups ordered by CE then CA; all members of each shown group are retained.

<details>
<summary>Indexed positions and files (bidirectional lookup)</summary>

| Position | CE | CA | Members | File ID and complete source identity |
|---|---:|---:|---:|---|
| G01 | 0 | 0 | 16 | F003: [src/avo/adapters/__init__.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/adapters/__init__.py) |
| G01 | 0 | 0 | 16 | F005: [src/avo/adapters/media/__init__.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/adapters/media/__init__.py) |
| G01 | 0 | 0 | 16 | F018: [src/avo/adapters/motion/__init__.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/adapters/motion/__init__.py) |
| G01 | 0 | 0 | 16 | F020: [src/avo/adapters/qc/__init__.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/adapters/qc/__init__.py) |
| G01 | 0 | 0 | 16 | F027: [src/avo/adapters/stubs/__init__.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/adapters/stubs/__init__.py) |
| G01 | 0 | 0 | 16 | F033: [src/avo/adapters/transcribe/__init__.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/adapters/transcribe/__init__.py) |
| G01 | 0 | 0 | 16 | F037: [src/avo/adapters/understand/__init__.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/adapters/understand/__init__.py) |
| G01 | 0 | 0 | 16 | F039: [src/avo/adapters/understand/cutting_alignment_worker.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/adapters/understand/cutting_alignment_worker.py) |
| G01 | 0 | 0 | 16 | F066: [src/avo/engine_install.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/engine_install.py) |
| G01 | 0 | 0 | 16 | F068: [src/avo/generate_sfx.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/generate_sfx.py) |
| G01 | 0 | 0 | 16 | F087: [src/avo/pack_transcripts.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/pack_transcripts.py) |
| G01 | 0 | 0 | 16 | F107: [src/avo/srt_to_centered_ass.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/srt_to_centered_ass.py) |
| G01 | 0 | 0 | 16 | F110: [src/avo/templates/__init__.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/templates/__init__.py) |
| G01 | 0 | 0 | 16 | F111: [src/avo/templates/shorts_hyperframes/__init__.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/templates/shorts_hyperframes/__init__.py) |
| G01 | 0 | 0 | 16 | F112: [src/avo/timeline/__init__.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/timeline/__init__.py) |
| G01 | 0 | 0 | 16 | F147: [src/avo/timeline/models.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/timeline/models.py) |
| G02 | 0 | 1 | 7 | F061: [src/avo/consume_mode.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/consume_mode.py) |
| G02 | 0 | 1 | 7 | F069: [src/avo/grade.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/grade.py) |
| G02 | 0 | 1 | 7 | F070: [src/avo/hardware.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/hardware.py) |
| G02 | 0 | 1 | 7 | F079: [src/avo/mcp/request_state.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/mcp/request_state.py) |
| G02 | 0 | 1 | 7 | F098: [src/avo/shorts_captions.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/shorts_captions.py) |
| G02 | 0 | 1 | 7 | F128: [src/avo/timeline/cutting_previews.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/timeline/cutting_previews.py) |
| G02 | 0 | 1 | 7 | F160: [src/avo/timeline/sync.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/timeline/sync.py) |
| G03 | 0 | 2 | 6 | F058: [src/avo/build_captions.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/build_captions.py) |
| G03 | 0 | 2 | 6 | F074: [src/avo/mcp/__init__.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/mcp/__init__.py) |
| G03 | 0 | 2 | 6 | F118: [src/avo/timeline/command_registry.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/timeline/command_registry.py) |
| G03 | 0 | 2 | 6 | F129: [src/avo/timeline/cutting_profiles.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/timeline/cutting_profiles.py) |
| G03 | 0 | 2 | 6 | F136: [src/avo/timeline/diff.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/timeline/diff.py) |
| G03 | 0 | 2 | 6 | F165: [src/avo/timeline_view.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/timeline_view.py) |
| G04 | 0 | 3 | 5 | F059: [src/avo/capabilities.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/capabilities.py) |
| G04 | 0 | 3 | 5 | F106: [src/avo/shorts_rules.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/shorts_rules.py) |
| G04 | 0 | 3 | 5 | F113: [src/avo/timeline/animation.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/timeline/animation.py) |
| G04 | 0 | 3 | 5 | F137: [src/avo/timeline/event_clock.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/timeline/event_clock.py) |
| G04 | 0 | 3 | 5 | F143: [src/avo/timeline/mapping.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/timeline/mapping.py) |
| G05 | 0 | 4 | 1 | F096: [src/avo/settings.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/settings.py) |
| G06 | 0 | 5 | 1 | F055: [src/avo/breath_control.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/breath_control.py) |
| G07 | 0 | 8 | 1 | F050: [src/avo/audio_restoration.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/audio_restoration.py) |
| G08 | 0 | 11 | 1 | F150: [src/avo/timeline/ports.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/timeline/ports.py) |
| G09 | 0 | 25 | 1 | F088: [src/avo/paths.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/paths.py) |
| G10 | 1 | 0 | 13 | F001: [src/avo/__init__.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/__init__.py) |
| G10 | 1 | 0 | 13 | F002: [src/avo/__main__.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/__main__.py) |
| G10 | 1 | 0 | 13 | F017: [src/avo/adapters/media/waveform.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/adapters/media/waveform.py) |
| G10 | 1 | 0 | 13 | F028: [src/avo/adapters/stubs/memory_ai_memory.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/adapters/stubs/memory_ai_memory.py) |
| G10 | 1 | 0 | 13 | F029: [src/avo/adapters/stubs/motion_hyperframes.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/adapters/stubs/motion_hyperframes.py) |
| G10 | 1 | 0 | 13 | F030: [src/avo/adapters/stubs/motion_remotion.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/adapters/stubs/motion_remotion.py) |
| G10 | 1 | 0 | 13 | F031: [src/avo/adapters/stubs/plan_speckit.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/adapters/stubs/plan_speckit.py) |
| G10 | 1 | 0 | 13 | F075: [src/avo/mcp/__main__.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/mcp/__main__.py) |
| G10 | 1 | 0 | 13 | F089: [src/avo/prepare_transcription.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/prepare_transcription.py) |
| G10 | 1 | 0 | 13 | F126: [src/avo/timeline/cutting_evaluation.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/timeline/cutting_evaluation.py) |
| G10 | 1 | 0 | 13 | F167: [src/avo/transcribe_batch.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/transcribe_batch.py) |
| G10 | 1 | 0 | 13 | F169: [src/avo/validate_dependencies.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/validate_dependencies.py) |
| G10 | 1 | 0 | 13 | F171: [src/avo/validate_usability.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/validate_usability.py) |
| G11 | 1 | 1 | 10 | F014: [src/avo/adapters/media/sync_materializer.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/adapters/media/sync_materializer.py) |
| G11 | 1 | 1 | 10 | F016: [src/avo/adapters/media/video_tracks.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/adapters/media/video_tracks.py) |
| G11 | 1 | 1 | 10 | F024: [src/avo/adapters/qc/source_fidelity.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/adapters/qc/source_fidelity.py) |
| G11 | 1 | 1 | 10 | F041: [src/avo/adapters/understand/cutting_semantics.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/adapters/understand/cutting_semantics.py) |
| G11 | 1 | 1 | 10 | F054: [src/avo/breath_analysis.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/breath_analysis.py) |
| G11 | 1 | 1 | 10 | F064: [src/avo/edl_timeline.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/edl_timeline.py) |
| G11 | 1 | 1 | 10 | F065: [src/avo/engine_cli.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/engine_cli.py) |
| G11 | 1 | 1 | 10 | F076: [src/avo/mcp/bridge.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/mcp/bridge.py) |
| G11 | 1 | 1 | 10 | F077: [src/avo/mcp/mrtr.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/mcp/mrtr.py) |
| G11 | 1 | 1 | 10 | F163: [src/avo/timeline/vision_review.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/timeline/vision_review.py) |
| G12 | 1 | 2 | 6 | F043: [src/avo/adapters/understand/watch_policy.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/adapters/understand/watch_policy.py) |
| G12 | 1 | 2 | 6 | F047: [src/avo/audio_eq.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/audio_eq.py) |
| G12 | 1 | 2 | 6 | F062: [src/avo/delivery_fidelity.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/delivery_fidelity.py) |
| G12 | 1 | 2 | 6 | F094: [src/avo/scratch.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/scratch.py) |
| G12 | 1 | 2 | 6 | F102: [src/avo/shorts_paths.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/shorts_paths.py) |
| G12 | 1 | 2 | 6 | F145: [src/avo/timeline/media_admission.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/timeline/media_admission.py) |
| G13 | 1 | 3 | 2 | F078: [src/avo/mcp/registry.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/mcp/registry.py) |
| G13 | 1 | 3 | 2 | F101: [src/avo/shorts_media.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/shorts_media.py) |
| G14 | 1 | 4 | 1 | F011: [src/avo/adapters/media/ffprobe.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/adapters/media/ffprobe.py) |
| G15 | 1 | 5 | 2 | F073: [src/avo/loudness_profiles.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/loudness_profiles.py) |
| G15 | 1 | 5 | 2 | F095: [src/avo/session.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/session.py) |
| G16 | 1 | 7 | 1 | F099: [src/avo/shorts_contract.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/shorts_contract.py) |
| G17 | 1 | 13 | 1 | F051: [src/avo/avo_state.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/avo_state.py) |
| G18 | 1 | 14 | 1 | F124: [src/avo/timeline/cutting_contracts.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/timeline/cutting_contracts.py) |
| G19 | 1 | 27 | 1 | F159: [src/avo/timeline/store.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/timeline/store.py) |
| G20 | 1 | 61 | 1 | F120: [src/avo/timeline/contracts.py](https://github.com/joaobispo2077/avo/blob/204b08f392a5b826a88a0ac5ced8d9880232b92d/src/avo/timeline/contracts.py) |

</details>


[Complete bidirectional file index: coupling-index.md (text archive)](kpi-detail:coupling-index.md)


**Findings and accepted debt**

- Dependency findings: 0 blocking; npm 0 critical / 2 high / 7 moderate / 0 low (MEASURED). [npm-audit-summary.json](https://github.com/joaobispo2077/avo/actions/runs/39084599780/artifacts/12119714109) (SHA-256 `e7a80b307070`); [deps-findings.json](https://github.com/joaobispo2077/avo/actions/runs/39084599780/artifacts/12119714109) (SHA-256 `c4769a32b091`); [pip-audit-raw.json](https://github.com/joaobispo2077/avo/actions/runs/39084599780/artifacts/12119714109) (SHA-256 `af0e7327c984`); [npm-audit-raw.json](https://github.com/joaobispo2077/avo/actions/runs/39084599780/artifacts/12119714109) (SHA-256 `f1c6c2dbda6b`)
- Dead-code findings: 150 reported; 0 unwaived (MEASURED). [deadcode.json](https://github.com/joaobispo2077/avo/actions/runs/39084599780/artifacts/12119714109) (SHA-256 `7a5e2691c97d`)
- Import boundaries: 5 kept; 0 broken (MEASURED). [gates/architecture/gate.json](https://github.com/joaobispo2077/avo/actions/runs/39084599780/artifacts/12119714109) (SHA-256 `1e567726f2ed`); [gates/architecture/gate.log](https://github.com/joaobispo2077/avo/actions/runs/39084599780/artifacts/12119714109) (SHA-256 `71ba52983dfe`)
- Dependency hoist plan: 24 proposed package changes (MEASURED). [dependency-tree.json](https://github.com/joaobispo2077/avo/actions/runs/39084599780/artifacts/12119714109) (SHA-256 `018e187972f7`)
- complexity: 178 configured entries; 178 matched findings; 178 unique affected path/name identities; stale: 0; 0 unwaived findings. Groups are non-additive; these counts are not defect removal.
- deadcode: 150 configured entries; 150 matched findings; 150 unique affected path/name identities; stale: 0; 0 unwaived findings. Groups are non-additive; these counts are not defect removal.

**Executed test evidence**

- repo-integration-tests: 114 passed / 0 failed / 0 errors / 1 skipped; 115 testcase events. MEASURED. Repeated events are not additional unique tests.
- repo-unit-tests: 2583 passed / 0 failed / 0 errors / 6 skipped; 2589 testcase events. MEASURED. Repeated events are not additional unique tests.

**Gate decisions**

![Gate decisions, policies and execution proof](kpi-chart:gate-decisions.png)

Status badges are categorical. Missing execution proof cannot certify a recorded PASS; recorded results stay labeled separately. Required jobs are listed separately below.

[Complete gate decisions and proof (text archive)](kpi-detail:gate-decisions.md)

| Gate | Decision | Policy | Execution evidence |
|---|---|---|---|
| Lint | **PASS** | Ruff (&#96;src/avo&#96;, &#96;tests&#96;, &#96;helpers&#96;) + ESLint | Captured exit 0. Numeric finding count not exported.. [gates/lint/gate.json](https://github.com/joaobispo2077/avo/actions/runs/39084599780/artifacts/12119714109) (SHA-256 `0bd6ade8c806`); [gates/lint/gate.log](https://github.com/joaobispo2077/avo/actions/runs/39084599780/artifacts/12119714109) (SHA-256 `1237e674bddf`) |
| Format | **PASS** | Ruff format --check + Prettier --check | Captured exit 0. Numeric finding count not exported.. [gates/format/gate.json](https://github.com/joaobispo2077/avo/actions/runs/39084599780/artifacts/12119714109) (SHA-256 `4e13d0040b34`); [gates/format/gate.log](https://github.com/joaobispo2077/avo/actions/runs/39084599780/artifacts/12119714109) (SHA-256 `dde3334d6c38`) |
| Coverage | **PASS** | pytest-cov fail-under on &#96;src/avo&#96;; Minimum 68%; comparison rounded to 0 decimal places | 71.42% · 18,421/25,794 executable lines. [gates/coverage/gate.json](https://github.com/joaobispo2077/avo/actions/runs/39084599780/artifacts/12119714109) (SHA-256 `2bdd224983a1`); [gates/coverage/gate.log](https://github.com/joaobispo2077/avo/actions/runs/39084599780/artifacts/12119714109) (SHA-256 `631fefc61592`) |
| Complexity | **PASS** | xenon max-absolute **B** · Ruff C901 ≤ 31 | 0 unwaived · 178 observed accepted findings. [gates/complexity/gate.json](https://github.com/joaobispo2077/avo/actions/runs/39084599780/artifacts/12119714109) (SHA-256 `ba41e00f6b22`); [gates/complexity/gate.log](https://github.com/joaobispo2077/avo/actions/runs/39084599780/artifacts/12119714109) (SHA-256 `238c15c415f3`) |
| Dependency audit | **PASS** | pip-audit on dev + MCP; unwaived Python advisories and npm critical block (&#96;deps-audit-allowlist.json&#96;); npm high/moderate/low reported | 0 blocking; npm 0 critical / 2 high / 7 moderate / 0 low. [gates/deps/gate.json](https://github.com/joaobispo2077/avo/actions/runs/39084599780/artifacts/12119714109) (SHA-256 `a73b6e263503`); [gates/deps/gate.log](https://github.com/joaobispo2077/avo/actions/runs/39084599780/artifacts/12119714109) (SHA-256 `de583a1b0458`) |
| Dead code | **PASS** | vulture confidence ≥ 60 (&#96;deadcode-allowlist.json&#96;) | 150 reported; 0 unwaived. [gates/deadcode/gate.json](https://github.com/joaobispo2077/avo/actions/runs/39084599780/artifacts/12119714109) (SHA-256 `539a773fb69c`); [gates/deadcode/gate.log](https://github.com/joaobispo2077/avo/actions/runs/39084599780/artifacts/12119714109) (SHA-256 `acc4eaadbd60`) |
| Duplication | **PASS** | jscpd on &#96;src/avo&#96;; Maximum 2% | 0.77% · 440/56,949 duplicated lines; 41 clone pairs. [gates/duplication/gate.json](https://github.com/joaobispo2077/avo/actions/runs/39084599780/artifacts/12119714109) (SHA-256 `b0f84f279361`); [gates/duplication/gate.log](https://github.com/joaobispo2077/avo/actions/runs/39084599780/artifacts/12119714109) (SHA-256 `3438f13a704b`) |
| Architecture | **PASS** | import-linter (&#96;.importlinter&#96;) | 5 kept; 0 broken. [gates/architecture/gate.json](https://github.com/joaobispo2077/avo/actions/runs/39084599780/artifacts/12119714109) (SHA-256 `1e567726f2ed`); [gates/architecture/gate.log](https://github.com/joaobispo2077/avo/actions/runs/39084599780/artifacts/12119714109) (SHA-256 `71ba52983dfe`) |
| Dependency tree | **PASS** | npm find-dupes · command fail blocks · hoist plan report-only | 24 proposed package changes · 1 additions / 6 removals / 17 changes; not applied. [gates/tree/gate.json](https://github.com/joaobispo2077/avo/actions/runs/39084599780/artifacts/12119714109) (SHA-256 `78ffae6bdace`); [gates/tree/gate.log](https://github.com/joaobispo2077/avo/actions/runs/39084599780/artifacts/12119714109) (SHA-256 `1e379d9100f1`) |
| Mutation | **PASS** | Complete accounting; Minimum 40%; light profile; selected Python modules | [mutation-metrics.json](https://github.com/joaobispo2077/avo/actions/runs/39084599780/artifacts/12120675814) (SHA-256 `ff8ab4bd0fcc`) |

<details>
<summary>Execution results</summary>

| Required job | Result | Test evidence |
|---|---|---|
| ci-readiness | **SUCCESS** | Job result; testcase counts not captured. Not captured |
| mutation-light | **SUCCESS** | Job result; testcase counts not captured. Not captured |
| prerequisites-gate | **SUCCESS** | Job result; testcase counts not captured. Not captured |
| repo-integration-tests | **SUCCESS** | 114 passed / 0 failed / 0 errors / 1 skipped; 115 JUnit testcases. MEASURED: Counts from actual native JUnit testcase events. [integration-tests.xml](https://github.com/joaobispo2077/avo/actions/runs/39084599780/artifacts/12119858518) (SHA-256 `838e4608f0ca`); [gates/integration-tests/gate.log](https://github.com/joaobispo2077/avo/actions/runs/39084599780/artifacts/12119858518) (SHA-256 `c1f519271bf8`) |
| repo-unit-tests | **SUCCESS** | 2583 passed / 0 failed / 0 errors / 6 skipped; 2589 JUnit testcases. MEASURED: Counts from actual native JUnit testcase events. [unit-tests.xml](https://github.com/joaobispo2077/avo/actions/runs/39084599780/artifacts/12120173685) (SHA-256 `2fa1b1757539`); [gates/unit-tests/gate.log](https://github.com/joaobispo2077/avo/actions/runs/39084599780/artifacts/12120173685) (SHA-256 `5aed1d98e4c4`) |
| software-quality | **SUCCESS** | Job result; testcase counts not captured. Not captured |
| usability-gate | **SUCCESS** | Job result; testcase counts not captured. Not captured |

Recorded skip/failure reasons: 1/1 non-passing testcase events shown; complete events and full reasons remain in the raw JUnit evidence.

| Suite / case | Outcome | Recorded reason |
|---|---|---|
| pytest:tests.integration.test_watch_adapter_runtime:test_bundled_watch_skill_executable_contract | skipped | watch-skill is not installed under tools/watch-skill /home/runner/work/avo/avo/tests/integration/test_watch_adapter_runtime.py:12: watch-skill is not installed under tools/watch-skill |


Recorded skip/failure reasons: 6/6 non-passing testcase events shown; complete events and full reasons remain in the raw JUnit evidence.

| Suite / case | Outcome | Recorded reason |
|---|---|---|
| pytest:tests.test_mcp_bridge:test_register_cli_tools_on_server | skipped | could not import 'mcp': No module named 'mcp' /home/runner/work/avo/avo/tests/test_mcp_bridge.py:376: could not import 'mcp': No module named 'mcp' |
| pytest:tests.test_mcp_meta:test_registered_meta_tools_on_server | skipped | could not import 'mcp': No module named 'mcp' /home/runner/work/avo/avo/tests/test_mcp_meta.py:102: could not import 'mcp': No module named 'mcp' |
| pytest:tests.test_mcp_package:test_create_server_registers_meta_and_all_cli_tools | skipped | could not import 'mcp': No module named 'mcp' /home/runner/work/avo/avo/tests/test_mcp_package.py:70: could not import 'mcp': No module named 'mcp' |
| pytest:tests.test_software_foundation.SoftwareFoundationTests:test_claude_foundation_skills_exist | skipped | .cursor/.claude dev tooling is gitignored in public checkouts /home/runner/work/avo/avo/tests/test_software_foundation.py:65: .cursor/.claude dev tooling is gitignored in public checkouts |
| pytest:tests.test_software_foundation.SoftwareFoundationTests:test_cursor_foundation_rules_exist | skipped | .cursor/.claude dev tooling is gitignored in public checkouts /home/runner/work/avo/avo/tests/test_software_foundation.py:44: .cursor/.claude dev tooling is gitignored in public checkouts |
| pytest:tests.test_software_foundation.SoftwareFoundationTests:test_cursor_skills_mirrored | skipped | .cursor/.claude dev tooling is gitignored in public checkouts /home/runner/work/avo/avo/tests/test_software_foundation.py:73: .cursor/.claude dev tooling is gitignored in public checkouts |


Successful execution is not a measured quality score. Uncaptured counts remain unavailable.

[Run logs and downloadable artifacts](https://github.com/joaobispo2077/avo/actions/runs/39084599780)

</details>

Diagnostic excerpt omitted for publication size. Complete observations and reasons remain in normalized JSON and linked text artifacts.

