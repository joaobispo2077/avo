---
name: avo-provider
description: >-
  Setup and configure an AVO provider — publishing destination, brand identity,
  palette, DESIGN.md, manifest metadata, scope, and external media paths. Load when
  the user creates a channel, adds a second provider for the same brand, runs
  /avo.provider, or asks what a provider is in this repo.
---

# AVO provider setup & configuration

Canonical concept doc: [`docs/providers.md`](../../docs/providers.md).

A **provider** is a publishing destination + brand scope (YouTube channel, TikTok
account, Shorts feed, podcast show). Each **video** remains a separate project;
the provider supplies defaults, brand tokens, external path roots, and ai-memory
learning boundaries.

## When to load

- User asks to **create**, **configure**, or **audit** a provider
- User invokes **`/avo.provider`**
- User wants **two providers for one channel** (e.g. long-form vs Shorts)
- Session start but **no provider exists yet** for the declared channel

## Diagnosis first (mandatory)

Before writing files, state:

1. **Platform** — `youtube` | `shorts` | `tiktok` | `instagram` | `x` | `podcast` | `generic`
2. **Slug** — lowercase kebab-case; must equal `providers/<slug>/` directory name
3. **Scope** — one sentence: what format this provider owns (e.g. "16:9 long-form tutorials")
4. **Split decision** — same slug vs new slug if user already has a provider for the brand
5. **External roots** — absolute `media.rawRoot`; optional asset library paths
6. **Language / model** — default transcription (`pt`, `en`, …) and optional Whisper tier

**One provider per platform/format family** works best. Same channel may use:

```text
providers/yt-channel-name-long-videos/
providers/yt-channel-name-short-videos/
```

Shared visual brand is fine (copy palette); **do not merge learning scope** unless
format rules truly match.

## Workflow

### 1. Scaffold (preferred)

```bash
bash scripts/new-provider.sh <slug> --kind <kind> --raw-root <abs-path> [--lang <code>]
```

```powershell
pwsh scripts/new-provider.ps1 -Name <slug> -Kind <kind> -RawRoot '<abs-path>' [-Lang <code>]
```

Refuses to overwrite an existing slug. Creates `avo.provider.json`, `DESIGN.md`,
`brand/palette.json`, `logo/.gitkeep`.

### 2. Complete the manifest (`avo.provider.json`)

Validate against [`providers/avo.provider.schema.json`](../../providers/avo.provider.schema.json).

| Field | Guidance |
| --- | --- |
| `displayName` | Human channel/show name |
| `description` | 1–3 sentences: audience, content type, tone |
| `scope` | Machine + human scope string (format + platform intent) |
| `platformUrl` | Optional canonical channel/account URL |
| `media.rawRoot` | **Required** external footage root (never inside AVO repo) |
| `assets.*` | External SFX/music/B-roll paths; `logos` → `providers/<slug>/logo` |
| `transcription` | Default language + optional Whisper size |
| `brand.design` / `brand.palette` | Relative paths to in-repo brand files |
| `routingOverrides` | Only if this provider needs different job routing than global config |

### 3. Brand files

**`DESIGN.md`** — agents read this for thumbnails, captions, lower-thirds, motion.
Minimum sections (see [`providers/_template/DESIGN.md`](../../providers/_template/DESIGN.md)):

- Brand essence (one sentence)
- Palette summary + contrast rules
- Typography stacks
- Caption / lower-third rules
- Motion language (density, easing)
- Do / Do not

**`brand/palette.json`** — machine-readable hex tokens:

```json
{
  "primary": "#122658",
  "secondary": "#64728C",
  "accent": "#19D8FF",
  "background": "#F7F9FC",
  "text": "#16181F",
  "roles": {
    "captionFill": "#F7F9FC",
    "captionStroke": "#16181F",
    "emphasis": "#371960"
  }
}
```

Keep `DESIGN.md` and `palette.json` in sync. Reference example:
[`providers/bishop/`](../../providers/bishop/) (local; gitignored in upstream).

**`logo/`** — SVG master + PNG exports; note clear-space in `DESIGN.md`.

### 4. Verify

```bash
# Manifest parses and provider resolves
python helpers/init_project.py --provider <slug> --raw-dir <test-path> --print -y

# List providers (directories with avo.provider.json, excluding _template)
python -c "from helpers.init_project import list_providers; print(list_providers())"
```

Confirm:

- [ ] Slug matches directory name and `name` field
- [ ] `media.rawRoot` is absolute and **outside** the AVO repo
- [ ] `DESIGN.md` + `palette.json` exist and paths match `brand.*` in manifest
- [ ] `scope` and `description` disambiguate this provider from siblings on the same channel
- [ ] Personal provider folder is gitignored (`providers/*/` except `_template`)

### 5. First video project

```bash
python helpers/init_project.py --provider <slug> --raw-dir <path-to-one-video-folder>
```

Writes `<rawDir>/avo.project.json`. All edit outputs go under `<rawDir>/edit/`.

## Multi-provider patterns

Read [`references/multi-provider-patterns.md`](references/multi-provider-patterns.md)
when the user mentions the same channel twice, Shorts vs long-form, or
cross-posting.

## Disclosure template (after setup)

Present a short summary the user can confirm:

```markdown
**Provider:** `<slug>` (`<kind>`)
**Display:** <displayName>
**Scope:** <scope>
**Raw root:** <media.rawRoot>
**Language:** <transcription.language>
**Brand:** DESIGN.md + palette.json at providers/<slug>/
**Learning:** ai-memory scoped to this slug only

**Alternatives considered:** <same slug vs split — one line why>
**Next:** drop footage in raw root → `init_project.py` → declare provider + rawDir in session
```

## Hard rules

1. **Never commit media** — manifest paths only
2. **Never use the AVO repo as `rawRoot`**
3. **Do not invent brand colors** when `DESIGN.md` / `palette.json` exist — read them
4. **Do not merge providers** to "simplify" unless format rules and learning scope truly match
5. Provider identity is **local** by default (gitignored); only `_template` ships publicly

## References

- [`docs/providers.md`](../../docs/providers.md) — what a provider is
- [`providers/README.md`](../../providers/README.md) — layout + schema table
- [`docs/avo-workflow.md`](../../docs/avo-workflow.md) §8 — learning scope
- [`references/manifest-fields.md`](references/manifest-fields.md) — field-by-field manifest
- [`references/multi-provider-patterns.md`](references/multi-provider-patterns.md) — long vs Shorts examples
