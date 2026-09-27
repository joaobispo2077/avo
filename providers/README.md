# AVO Providers

A **provider** is a publishing destination and brand identity — a YouTube
channel, TikTok account, Instagram profile, podcast, and so on. AVO scopes its
self-learning by provider (it learns across a provider's videos) while each
individual video stays a separate project.

**Full concept guide:** [`docs/providers.md`](../docs/providers.md)  
**Agent skill:** `avo-provider` / `/avo.provider`

Provider **identity lives in this repo**; provider **media stays external**.

## Layout

```
providers/
  avo.provider.schema.json   # JSON Schema for every provider manifest
  _template/                 # copy this to start a new provider (or use the scaffolder)
    avo.provider.json        # manifest (validated against the schema)
    DESIGN.md                # provider design language
    logo/                    # SVG source + PNG exports (.gitkeep placeholder)
    brand/
      palette.json           # machine-readable brand tokens
    learndowns/              # exported per-video learndowns (index.json + entries)
    videos/                  # optional in-repo registry stubs (paths only)
      <video-id>/
        video.json           # points at external rawDir; no media here
  <name>/                    # one directory per provider (lowercase kebab-case)
    ...same shape as _template...
    videos.index.json        # generated catalog (provider root)
```

## Manifest — `avo.provider.json`

Validated against [`avo.provider.schema.json`](./avo.provider.schema.json).

| Field | Required | Notes |
| --- | --- | --- |
| `name` | yes | Slug; must equal the `providers/<name>/` directory name. |
| `displayName` | no | Human-friendly name. |
| `kind` | yes | `youtube` \| `tiktok` \| `instagram` \| `x` \| `podcast` \| `shorts` \| `generic`. |
| `description` | no | Short channel/account description. |
| `scope` | no | Format intent (long-form, Shorts, podcast episodes, …); ai-memory boundary. |
| `platformUrl` | no | Optional canonical channel/account URL. |
| `media.rawRoot` | yes | **EXTERNAL** absolute path to raw footage. Never inside this repo. |
| `media.editRoot` | no | Optional external edit/output root (defaults to `<rawRoot>/edit`). |
| `assets.{sfx,music,inserts,graphics}` | no | **EXTERNAL** paths to asset libraries. |
| `assets.logos` | no | Usually the in-repo path `providers/<name>/logo`. |
| `transcription.language` | no | faster-whisper language code (chosen at setup, e.g. `pt`, `en`). |
| `transcription.model` | no | Preferred Whisper model size. |
| `brand.design` / `brand.palette` | no | Paths to `DESIGN.md` / `brand/palette.json`. |
| `routingOverrides` | no | Per-provider patch over `avo.config.json` routing. |

### Media is external — always

The manifest stores **paths only**. No raw or edit media is ever committed;
`media/`, `edit/`, and provider footage roots are gitignored. Brand identity
(design, logo, palette) is shareable and tracked; personal footage is not.

## Creating a provider

Use the scaffolder (preferred):

```bash
# macOS / Linux / WSL
bash scripts/new-provider.sh <name> --kind youtube --raw-root /abs/path/to/footage
```

```powershell
# Windows / WSL-from-PowerShell
pwsh scripts/new-provider.ps1 -Name <name> -Kind youtube -RawRoot C:\abs\path\to\footage
```

Or copy `_template/` to `providers/<name>/` by hand and edit the manifest.

**Personal providers are gitignored.** Only `providers/_template/` and the schema
ship in the public repo. Your real channel directory (e.g. `providers/my-channel/`)
stays on disk locally and is never committed.

## Timeline learning

Completed videos may export immutable sanitized learning under
`providers/<name>/learndowns/<entry>/timeline-learning/`. The active index points
to one draft or final `TimelineLearningSnapshot`, which binds the final iteration
ledger, candidate, regression, reconstruction, and approved-master identities.
It contains prevention rules and neutral rework taxonomy, but no source media,
transcript body, private absolute path, editable timeline, secret, or inherited
approval. New projects load only final snapshots as contextual guidance.

```json
{
  "snapshotId": "timeline-learning-0123456789ab",
  "status": "final",
  "iterationLedgerHash": "<sha256>",
  "candidateSnapshotHash": "<sha256>",
  "reconstructionBundleHash": "<sha256>",
  "masterFingerprint": {"sha256": "<sha256>", "sizeBytes": 123},
  "taxonomy": [],
  "preventionRules": [],
  "snapshotHash": "<sha256>"
}
```

The complete contract is [`avo.timeline-learning.schema.json`](../schemas/avo.timeline-learning.schema.json).

## Reusable provider animation components

Reusable HyperFrames behavior is proposed from approved project-local code,
sanitized, rights-checked, validated with at least two neutral fixtures, and
explicitly approved before publication. Immutable semantic versions live under
`providers/<name>/animations/hyperframes/<kitId>/versions/<version>/`; the
provider catalog validates against
[`avo.animation-library.schema.json`](./avo.animation-library.schema.json).

A published component declares typed parameters, design tokens, lifecycle,
SFX relationships, source-file fingerprints, an exact dependency lock, neutral
fixtures, per-dependency rights, accessibility behavior, provenance, manifest
integrity, and lifecycle state. Missing, ambiguous, expired, revoked, or
non-portable rights block new use. The same version cannot be replaced with
different bytes, and deprecation never deletes a referenced version.

```json
{
  "patternId": "chapter-card",
  "version": "1.1.0",
  "parameterSchema": {
    "type": "object",
    "required": ["label"],
    "properties": {"label": {"type": "string"}}
  },
  "lifecycle": {
    "preEntry": "hidden",
    "entrance": "pop",
    "hold": "readable",
    "exit": "fade",
    "reducedMotion": "fade"
  },
  "manifestSha256": "<sha256>",
  "lifecycleState": "active"
}
```

Reuse always creates a fresh project-local `ComponentInstance` with exact kit
version/hash, current text and assets, current BMap/Tracks events and safe areas,
new rights evidence, generated-file fingerprints, fresh QC, and fresh approval.
No timing, media, review, rights assumption, or approval is inherited from the
originating video.
