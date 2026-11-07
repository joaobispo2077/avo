# AVO roadmap

Public product roadmap for the AVO orchestrator. For shipped SemVer history see
[`CHANGELOG.md`](../CHANGELOG.md). For engine upstream tracking see
[`docs/engine-vs-orchestrator.md`](engine-vs-orchestrator.md).

---

## Shipped recently

- **Wave A capabilities (docs):** README hero + compact nav, GitHub issue templates, `/avo.issues`, `/avo.supporters`, `/avo.creators`, ROADMAP BL-006–017 rows
- **Wave 4 pipeline commands (docs):** `/avo.motion-graphics`, `/avo.general`, `/avo.remotion-port`, `/avo.screencast`, `/avo.format`, `/avo.framework`, `/avo.grade`
- **Wave 3 pipeline commands (docs):** `/avo.launch`, `/avo.music-video`, `/avo.talking-head`, `/avo.figma`, `/avo.end-screen`, `/avo.color`, `/avo.sync`, `/avo.media`
- **Wave 2 pipeline commands (docs):** `/avo.rights`, `/avo.audio-qc`, `/avo.chapters`, `/avo.thumbnail`, `/avo.podcast-clip`, `/avo.trailer`, content routers (`/avo.pr-video`, `/avo.changelog-video`, `/avo.explainer`, `/avo.slideshow`), optional `/avo.retention`, `/avo.animation-qc`
- Review templates: rights, audio, end-screen, color, sync checklists; grouped `/avo.help`
- **Wave 1:** `/avo.captions`, `/avo.deliver`, `/avo.shorts`, `/avo.reframe`
- Local `/avo.stats`, wrap reports, and privacy documentation
- semantic-release pipeline (alpha on `develop`, stable on `release`)
- Canonical pipeline references under `agent-skills/avo-pipeline/`

Specs: [`avo-wave4-skills`](../specs/active/avo-wave4-skills/feature-brief.md) · [`avo-wave3-skills`](../specs/active/avo-wave3-skills/feature-brief.md) · [`avo-future-skills`](../specs/active/avo-future-skills/)

---

## In progress / near term

- **BL-010 implementation delivered, acceptance pending:** visual folder review, approved safe moves, searchable footage and bounded local transcription. The five-person comprehension study and full reference-scale performance acceptance remain pending; see [library organization](library-organize.md).
- Provider-scoped learning and manifest hardening
- Expanded command parity tests and install smoke coverage
- Documentation index cleanup (`docs/README.md`, delivery specs)

---

## Roadmap (sponsor-friendly)

AVO empowers editors — it does not replace Premiere, DaVinci, or CapCut. The
planned slash commands below extend **library workflows**, **cost transparency**,
and **NLE export** so you ship more videos locally while keeping craft in your
editor of choice.

Each item has a detailed brief under `specs/backlog/` when present locally.
Use [Sponsor](../README.md#sponsor) to help prioritize.

### Engine & delivery

| ID | Title | Summary | Future slash surface |
| -- | ----- | ------- | -------------------- |
| BL-001 | Upscaling low-quality source | Controlled upscale path for phone/Zoom archives | `/avo.upscale` (when engine ships) |
| BL-002 | Higher-than-source output | Opt-in delivery above camera native resolution | deliver flag + config |
| BL-003 | Provider voice profile | Sound like the creator on dubs, with consent | part of `/avo.locale` |
| BL-004 | Locale export pack | PT-BR, ES, JA, ZH captions-first from one English master | `/avo.locale` |
| BL-005 | Multi-audio delivery manifest | Per-locale tracks + manifest in deliver folder | `/avo.locale` deliver step |

### Discovery & community (Wave A — shipped)

| ID | Title | Summary | Future slash surface |
| -- | ----- | ------- | -------------------- |
| BL-006 | README hero + compact nav | Empower-editors positioning, 2-row inline nav, slim Documentation § | _(docs — shipped)_ |
| BL-007 | Issue templates + `/avo.issues` | GitHub YAML forms + agent-guided issue prep | `/avo.issues` |
| BL-008 | Sponsor surface | Sponsorship links + roadmap prioritization policy | `/avo.supporters` |
| BL-009 | Creators showcase | Opt-in curated channel list | `/avo.creators` |

### Library, transparency & interchange

| ID | Title | Summary | Slash surface / status |
| -- | ----- | ------- | -------------------- |
| BL-010 | [Library organize v1](library-organize.md) | Visual folder review, approved moves, search and bounded local batches | `/avo.organize` _(implementation delivered; acceptance pending)_ |
| BL-011 | Composition planning | Selected clips → brief + draft EDL (no auto-render) | `/avo.composition` |
| BL-012 | Voiceover lite path | Merge clips + external VO + EQ (no motion) | `/avo.voiceover` _(shipped)_ |
| BL-013 | Multicam metadata | CAM1/CAM2/CAM3 registration in `multicam.json` | `/avo.multicam` |
| BL-014 | Agent cost transparency | Local token/USD estimates + learning curve | `/avo.costs` (`/avo.metrics` alias) |
| BL-015 | Concurrent workstreams | Multiple videos per provider via external `rawDir` | docs + `avo.videos` _(shipped)_ |
| BL-016 | LUT library | `.cube` import/apply + NLE export notes | `/avo.luts` |
| BL-017 | NLE export pack | JSON EDL → CMX EDL → FCP XML 1.3 interchange | `/avo.exports` |
| BL-018 | avo.cloud (weak-hardware path) | Optional remote AVO when below local model floor; cloud MCP auth last; never blocks local | remote runtime + cloud `avo.mcp` |
| BL-019 | Configurable model sources | Select model IDs, local caches/files, endpoints, and runtime settings globally or per provider/project; disclose the resolved source | `/avo.models` _(implemented; SemVer pending)_ |

**Locale (`/avo.locale`):** design stub only — [`locale-stub.md`](../specs/backlog/locale-stub.md). **Do not implement** until BL-003–005 engine jobs ship.

Brief paths (when checked out): `specs/backlog/<slug>.md`

---

## Editing craft and motion planning (research proposals)

Extracted from the 2026-11-04
[fluxo-de-edicao comparison](fluxo-de-edicao-comparison.md). These items are
**proposed, not implemented or scheduled**. Audio/video Tracks, BMap cue timing,
Animation strategy and storyboard templates already exist; the proposals reuse
them. Listed order is a prioritization recommendation, not a delivery promise.

Full scope is specified together in the local working feature
`specs/017-editing-craft-parity/spec.md`, including track/asset review, supported
editor feedback and bounded recovery of speech omitted by transcription. Its
`gap-coverage.md` maps reference practices to requirements and existing
capability boundaries. Working specs remain local under the repository's
existing ignore policy; they are not published feature documentation.

Planned defaults: motion maps and linked lightweight storyboards are built in
for applicable motion planning/review. Camera movement, face anchoring, sound
matching, reference analysis, spoken notes/recovery and editor handoff remain
selected options. Default presentation does not start optional tools or alter
an existing edit.

| ID | Proposal | Smallest useful outcome | Existing alignment |
| -- | -------- | ----------------------- | ------------------ |
| BL-020 | [Motion map and storyboard review](../specs/backlog/motion-planning-review.md) | Joined, revision-bound motion plan, storyboard cards and stable-ID feedback | BMap + Tracks + Animation; complements BL-011 |
| BL-021 | [Optional talking-head camera](../specs/backlog/talking-head-camera.md) | Reviewable zoom in/out, push/pull and overlay-aware reframing | Extend beyond current Shorts punches; optional BL-017 keyframe export |
| BL-022 | [Measured motion references](../specs/backlog/reference-motion-analysis.md) | Bounded camera/element timing measurements with uncertainty | Existing Direction/Briefstart and beat-edit reference analysis |
| BL-023 | [Local SFX library matching](../specs/backlog/sfx-library-matching.md) | Licensed acoustic metadata, event-based recommendations and perceptual alignment | Existing event clock/mixer/media resolution; coordinate with BL-010 |
| BL-024 | [Spoken editing notes](../specs/backlog/spoken-edit-notes.md) | Configured note extraction and reviewed source-anchored proposals | Existing transcription, cutting and review services |

Also refine existing [BL-011 composition planning](../specs/backlog/composition-command.md)
and [BL-017 NLE exports](../specs/backlog/nle-exports.md) with the comparison's
planning and editor-interchange lessons. Keep camera movement and SFX optional;
do not adopt automatic zooms or continuous drift as universal defaults.

---

## Possible technical debt (not scheduled)

Optional follow-ups from `/ponytail-review` on BL-019 after `5ba4e38`. They are **possible** debt, not blockers, not a product row, and not a promise to shrink. Resolve only when already editing the same files. Estimated ceiling if all land: about **−103 lines**.

| Where | Kind | Cut | Replacement |
| ----- | ---- | --- | ----------- |
| `watch_skill.py` `_require_bonsai_runtime` + pin `resolve_job` | yagni | Second Bonsai checker (`_dict_at` / `_env_or` / `_bonsai_paths` / `_missing_file`) | `preflight(resolved)` and map `PreflightError` → `ToolError` |
| `faster_whisper.py` `_argv_with_model` | yagni | One-flag wrapper | `_argv_with_option(argv, "--model", resolved.id)` |
| `faster_whisper.py` pin unwrap | shrink | Eight-line `isinstance` source/runtime unwrap | `resolved.pin.get("source") or {}` |
| `models.py` `_job_catalog_key` | delete | Twin of `job_catalog_key` | `from avo.model_sources import job_catalog_key` |
| `model_sources.py` `_SCOPE_RANK["hardware"]` | delete | Rank never read after `_apply_hardware` | nothing |
| `model_sources.py` `_copy_source` | stdlib | Hand-copied nested source | `copy.deepcopy(source)` |
| `model_sources.py` disclosure `servedName` | delete | Top-level copy of `endpoint.servedName` | keep the nested field |
| `model_sources.py` `_reuse_status` | yagni | `downloaded-approved` though nothing downloads | `"reuse": "existing"` |
| `model_sources.py` `_missing_or_download` | yagni | Third raise when `allowDownload` and online; still fails | explicit → `missing_artifact`, else → `download_disallowed` |
| `avo.model-source.schema.json` `repo` / `revision` | yagni | Schema accepts fields the resolver never reads | drop until a reader exists |

---

## Upstream engine

AVO bundles and adapts the [video-use](https://github.com/browser-use/video-use)
engine. Upstream diff snapshots live under `specs/upstream-diffs/video-use/`
(see [`docs/adapters.md`](adapters.md)). Engine API changes land in `src/avo/`
with compatibility shims in `helpers/` until v0.2.0.

---

## How to propose work

1. Run **`/avo.issues`** with your agent, or open the [issue template chooser](https://github.com/joaobispo2077/avo/issues/new/choose).
2. For large features, use Spec Kit in your footage folder or SDD specs locally.
3. Link sponsor interest in the issue if you want something moved up the queue (`/avo.supporters`).

## Recorded video costs

Use /avo.costs (/avo.metrics alias) during editing or with --history after completion. Learndown and cleanup automatically display saved cost/token summaries with coverage and cutoff. Model/service switches preserve original usage attribution. [Collection, fallbacks and pricing disclosures](video-cost-transparency.md).
