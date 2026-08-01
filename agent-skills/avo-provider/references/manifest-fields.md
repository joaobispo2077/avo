# Provider manifest fields

Schema: [`providers/avo.provider.schema.json`](../../../providers/avo.provider.schema.json)

## Identity

| Field | Required | Example |
| --- | --- | --- |
| `name` | yes | `yt-acme-long` — must match `providers/<name>/` |
| `displayName` | no | `Acme Engineering` |
| `kind` | yes | `youtube` \| `shorts` \| `tiktok` \| `instagram` \| `x` \| `podcast` \| `generic` |
| `description` | no | Human summary of channel content and tone |
| `scope` | no | `16:9 long-form tutorials, 10–25 min` — learning + routing boundary |
| `platformUrl` | no | `https://youtube.com/@acme` |

## Media (external only)

| Field | Required | Notes |
| --- | --- | --- |
| `media.rawRoot` | yes | Absolute path to footage library; never in AVO repo |
| `media.editRoot` | no | Defaults to `<rawRoot>/edit` per video |

## Assets

Paths only. Empty string = unset.

| Key | Typical use |
| --- | --- |
| `sfx` | Licensed SFX root |
| `music` | Music library root |
| `inserts` | B-roll / insert clips |
| `graphics` | Overlays, PNG sequences |
| `logos` | Usually `providers/<slug>/logo` (in-repo) |

Per-video overrides go in `avo.project.json` → `assets`.

## Transcription defaults

| Field | Notes |
| --- | --- |
| `transcription.language` | faster-whisper code (`en`, `pt`, …) |
| `transcription.model` | Optional Whisper size (`small`, `medium`, …) |

Overridden by setup state, project file, or hardware advisory (see model transparency docs).

## Brand pointers

| Field | Points to |
| --- | --- |
| `brand.design` | `providers/<slug>/DESIGN.md` |
| `brand.palette` | `providers/<slug>/brand/palette.json` |

Agents load these before captions, motion, or thumbnail work.

## routingOverrides

Partial `avo.config.json` patch for this provider only — job routing, confidence
gates, transcription backend. Keep empty unless the provider genuinely needs a
different default (e.g. paid transcribe for one show).
