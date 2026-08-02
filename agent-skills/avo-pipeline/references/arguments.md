# Shared /avo.* arguments

Parse these from the user's slash command or ask once before executing.

## Required context

```text
Provider: <channel-or-brand>
<footage location — plain language or path>
```

**Accept any of these from the user** (map to `rawDir` internally):

| User says | Becomes |
| --------- | ------- |
| `The footage is at C:/Videos/my-review` | `rawDir` = that path |
| `The footage is in this folder` | `rawDir` = workspace folder the user opened |
| `rawDir: /abs/path` | power-user form; use as-is |

`rawDir` is the workflow root. All session output goes in `<rawDir>/edit/`. Never write inside the AVO repo.

## Non-footage workflows (content routers)

For `/avo.pr-video`, `/avo.changelog-video`, `/avo.explainer`, `/avo.slideshow`:

```text
ProjectDir: /path/to/project    # workflow root (= rawDir semantics)
Source: <url-or-path>         # PR URL, changelog.md, article, slide outline
```

| Router | Source example |
| ------ | -------------- |
| `/avo.pr-video` | `https://github.com/owner/repo/pull/123` |
| `/avo.changelog-video` | `/path/to/weekly-changelog.md` |
| `/avo.explainer` | `/path/to/article.md` |
| `/avo.slideshow` | `/path/to/slides-outline.md` |

**Private repos / tokens:** PR and private URLs require authenticated `gh` or local paths — warn user; never log secrets.

## Asset paths

```text
Footage: <file-or-folder>     # primary source
SFX: <file-or-folder>         # optional
B-roll: <file-or-folder>      # optional
Music: <file-or-folder>       # optional
Logo: <path>                  # optional; often providers/<name>/logo
Transcript: <path>            # optional; chapters stage
```

Record paths in `avo.project.json` under `assets` when the project file exists.

## Caption identity

For `/avo.captions`, `/avo.shorts`, and `/avo.podcast-clip`:

```text
identity: anchor
```

Also accept `--identity anchor`. See embedded-captions `CATALOG.md`.

## Time windows

For `/avo.audit`, scoped trim, `/avo.reframe`, and `/avo.podcast-clip`:

```text
from: 9:30
to: 9:35
```

Also accept `9:30-9:35` or `--from 9:30 --to 9:35`.

## Flags

| Flag | Commands | Meaning |
| ---- | -------- | ------- |
| `--skip-motion` | pipeline, trim, shorts, podcast-clip | Stop after edit master / skip motion phase |
| `--identity NAME` | captions, shorts, podcast-clip | Caption identity (e.g. `anchor`) |
| `--from-master` | shorts | Extract from approved long-form master via reframe |
| `--max-duration N` | shorts, podcast-clip, trailer | Shorts default 60; trailer default 90; warn/block over N without EDITLOG override |
| `--vertical` | podcast-clip | Delegate to reframe for 9:16 from long-form master |
| `--count N` | thumbnail | Frame still count (default ≥3) |
| `--preview` | pipeline, trim, motion, chapters, trailer, animation-qc | Stay on proofs / draft-only where applicable |
| `--early` | rights | Post-trim rights pass for clip-heavy formats (react, news, documentary) |
| `--only-transcription` | audit | Check transcript/word timing only |
| `--only-video` | audit | Check picture/sync only |
| `--youtube` | guidelines | YouTube format playbooks |
| `--eq` | guidelines | Audio EQ/restoration/loudness |
| `--tiktok` | guidelines | TikTok vertical short-form |
| `--shorts` | guidelines | YouTube Shorts |
| `--force` | transcribe | Re-transcribe despite cache |
| `--dry-run` | cleanup | List deletes only |
| `--json` | telemetry | Machine-readable line only |
| `--section` | help | Filter help index group |

## Canonical rules

Always load before executing:

- [`AGENTS.md`](../../../AGENTS.md)
- [`SKILL.md`](../../../SKILL.md)
- [`docs/avo-workflow.md`](../../../docs/avo-workflow.md)

**Note:** `/avo.deliver` covers the full master. Use `/avo.audit` with `from`/`to` for window QC only.
