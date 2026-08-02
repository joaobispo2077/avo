# What is an AVO provider?

In AVO, a **provider** is a **publishing destination and brand identity** — not a
single video, not the footage folder, and not the orchestrator repo itself.

Examples:

| Provider slug | What it represents |
| --- | --- |
| `bishop` | YouTube channel "Bishop" — brand, palette, default language |
| `yt-acme-long` | Long-form YouTube for channel Acme (16:9, chapters, slower pacing) |
| `yt-acme-shorts` | Shorts/Reels for the same human brand, different format rules |
| `acme-tiktok` | TikTok account with vertical-safe captions and faster cuts |

Each **video** is still its own project (`avo.project.json` + `rawDir`). The
provider supplies defaults that every video for that destination inherits.

---

## Provider vs project vs repo

```text
AVO repo (orchestrator)
└── providers/<slug>/          ← identity + brand (in-repo paths only)
      avo.provider.json        ← manifest
      DESIGN.md                ← design language for agents/editors
      brand/palette.json         ← machine-readable colors
      logo/                      ← SVG + PNG exports

External disk (gitignored media)
└── /path/to/footage/          ← provider.media.rawRoot
      my-video-001/              ← one video = one rawDir
        avo.project.json         ← tags provider + asset paths for this video
        edit/                    ← all session outputs live here
```

| Layer | Lives where | Purpose |
| --- | --- | --- |
| **AVO repo** | `helpers/`, `docs/`, skills | Orchestration, adapters, gates |
| **Provider** | `providers/<slug>/` | Brand, defaults, external path roots, learning scope |
| **Project** | Next to raw footage | One video's `rawDir`, overrides, working title |

**Media never enters the repo.** The manifest stores **paths only**
(`media.rawRoot`, asset libraries). Brand files (design, logo, palette) are
tracked locally; personal provider folders are gitignored by default
(see [`providers/README.md`](../providers/README.md)).

---

## One provider per platform (recommended)

The same human channel *can* span multiple providers, but AVO works best when each
provider maps to **one platform + one format family**:

- Different **caption safe zones** (16:9 vs 9:16)
- Different **pacing playbooks** (long-form vs Shorts)
- Different **motion density** and thumbnail grammar
- Different **ai-memory learndown** (cuts that work in Shorts may harm long-form)

### Same channel, two providers (supported pattern)

```text
providers/
  yt-channel-name-long-videos/
    avo.provider.json    kind: youtube, scope: long-form
  yt-channel-name-short-videos/
    avo.provider.json    kind: shorts, scope: vertical-clips
```

Both may share visual brand (copy palette, fork `DESIGN.md`), but keep **separate
slugs** so learning, routing overrides, and default transcription settings stay
isolated.

Use **one provider** when duration/style differences are minor (e.g. 8–20 min
tutorials on the same YouTube channel). Split when format rules diverge enough
that captions, pacing, and QC checklists differ.

---

## What the manifest carries

[`providers/avo.provider.schema.json`](../providers/avo.provider.schema.json) defines
`avo.provider.json`. Key groups:

| Group | Examples | Notes |
| --- | --- | --- |
| **Identity** | `name`, `displayName`, `kind`, `description`, `scope` | Slug must match directory name |
| **Media roots** | `media.rawRoot`, `media.editRoot` | External absolute paths |
| **Assets** | `assets.sfx`, `music`, `inserts`, `graphics`, `logos` | External libs; logos usually in-repo |
| **Transcription** | `transcription.language`, `model` | Provider default; overridable per video |
| **Audio restoration** | `restoration_default_pct` | Optional 0–100% default NR for speech (Standard = 35); EDL overrides win |
| **Brand** | `brand.design`, `brand.palette` | Pointers to `DESIGN.md` + `palette.json` |
| **Routing** | `routingOverrides` | Patch over shared `avo.config.json` |

Resolution order for a video project:

1. `avo.config.json` (global defaults)
2. `providers/<slug>/avo.provider.json` (provider)
3. `<rawDir>/avo.project.json` (this video only)

---

## Learning scope (ai-memory)

AVO consolidates learndowns **per provider**, not per video. All videos tagged
`provider: yt-acme-long` contribute to the same memory scope; Shorts on
`yt-acme-shorts` do not pollute long-form decisions (and vice versa).

**Filesystem export:** each wrap (draft or final) also writes under
`providers/<slug>/learndowns/<YYYYMMDD-topic>/` — `learndown.json`, `learndown.md`,
wrap copies, and a provider-level `index.json` catalog. ai-memory is optional;
the repo export is the durable catalog agents can grep. Backfill:
`python -m avo.learndown_export backfill --wrap-json <rawDir>/avo.wrap.draft.json`.

That is why slug choice matters: it is the **learning boundary**, not just a folder name.

---

## Creating a provider

Preferred — scaffolder:

```bash
bash scripts/new-provider.sh yt-channel-name-long-videos \
  --kind youtube \
  --raw-root /abs/path/to/long-form-footage \
  --lang en
```

```powershell
pwsh scripts/new-provider.ps1 -Name yt-channel-name-short-videos `
  -Kind shorts -RawRoot 'D:\footage\acme-shorts' -Lang en
```

Then edit:

1. `avo.provider.json` — `displayName`, `description`, `scope`, asset paths
2. `DESIGN.md` — voice, typography, captions, motion language
3. `brand/palette.json` — hex tokens for captions, lower-thirds, motion
4. `logo/` — SVG source + PNG exports

Bootstrap a video project:

```bash
python -m avo.init_project --provider yt-channel-name-long-videos \
  --raw-dir /abs/path/to/long-form-footage/my-video-001
```

List existing providers:

```bash
python -m avo.init_project --provider __list__  # not implemented — use ls providers/
```

---

## Agent skill

Load **`avo-provider`** when the user wants to create, configure, audit, or explain
a provider. See [`agent-skills/avo-provider/SKILL.md`](../agent-skills/avo-provider/SKILL.md).

Slash command: **`/avo.provider`** (configure or create).

---

## Related docs

- [`providers/README.md`](../providers/README.md) — directory layout
- [`docs/avo-workflow.md`](avo-workflow.md) §8 — provider-scoped learning
- [`docs/model-transparency.md`](model-transparency.md) — model tiers per job
