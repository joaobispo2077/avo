# AVO roadmap

Public product roadmap for the AVO orchestrator. For shipped SemVer history see
[`CHANGELOG.md`](../CHANGELOG.md). For engine upstream tracking see
[`docs/engine-vs-orchestrator.md`](engine-vs-orchestrator.md).

---

## Shipped recently

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

- Provider-scoped learning and manifest hardening
- Expanded command parity tests and install smoke coverage
- Documentation index cleanup (`docs/README.md`, delivery specs)

---

## Backlog (sponsor-friendly)

Each item has a detailed brief under `specs/backlog/` when present locally.
Use [Sponsor](../README.md#sponsor) to help prioritize.

| ID | Title | Summary | Future slash surface |
| -- | ----- | ------- | -------------------- |
| BL-001 | Upscaling low-quality source | Controlled upscale path for phone/Zoom archives | `/avo.upscale` (when engine ships) |
| BL-002 | Higher-than-source output | Opt-in delivery above camera native resolution | deliver flag + config |
| BL-003 | Provider voice profile | Sound like the creator on dubs, with consent | part of `/avo.locale` |
| BL-004 | Locale export pack | PT-BR, ES, JA, ZH captions-first from one English master | `/avo.locale` |
| BL-005 | Multi-audio delivery manifest | Per-locale tracks + manifest in deliver folder | `/avo.locale` deliver step |

**Locale (`/avo.locale`):** design stub only — [`locale-stub.md`](../specs/backlog/locale-stub.md). **Do not implement** until BL-003–005 engine jobs ship.

Brief paths (when checked out): `specs/backlog/<slug>.md`

---

## Upstream engine

AVO bundles and adapts the [video-use](https://github.com/browser-use/video-use)
engine. Upstream diff snapshots live under `specs/upstream-diffs/video-use/`
(see [`docs/adapters.md`](adapters.md)). Engine API changes land in `src/avo/`
with compatibility shims in `helpers/` until v0.2.0.

---

## How to propose work

1. Open a GitHub issue with problem, user story, and acceptance criteria.
2. For large features, use Spec Kit in your footage folder or SDD specs locally.
3. Link sponsor interest in the issue if you want something moved up the queue.
