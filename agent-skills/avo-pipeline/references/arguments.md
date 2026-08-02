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

## Asset paths

```text
Footage: <file-or-folder>     # primary source
SFX: <file-or-folder>         # optional
B-roll: <file-or-folder>      # optional
Music: <file-or-folder>       # optional
Logo: <path>                  # optional; often providers/<name>/logo
```

Record paths in `avo.project.json` under `assets` when the project file exists.

## Caption identity

For `/avo.captions` and `/avo.shorts`:

```text
identity: anchor
```

Also accept `--identity anchor`. See embedded-captions `CATALOG.md`.

## Time windows

For `/avo.audit`, scoped trim, and `/avo.reframe`:

```text
from: 9:30
to: 9:35
```

Also accept `9:30-9:35` or `--from 9:30 --to 9:35`.

## Flags

| Flag | Commands | Meaning |
| ---- | -------- | ------- |
| `--skip-motion` | pipeline, trim, shorts | Stop after edit master / skip motion phase |
| `--identity NAME` | captions, shorts | Caption identity (e.g. `anchor`) |
| `--from-master` | shorts | Extract from approved long-form master via reframe |
| `--max-duration N` | shorts | Default 60; warn/block promotion over N seconds |
| `--only-transcription` | audit | Check transcript/word timing only |
| `--only-video` | audit | Check picture/sync only |
| `--preview` | pipeline, trim, motion | Stay on 360p/720p proofs |
| `--youtube` | guidelines | YouTube format playbooks |
| `--eq` | guidelines | Audio EQ/restoration/loudness |
| `--tiktok` | guidelines | TikTok vertical short-form |
| `--shorts` | guidelines | YouTube Shorts |
| `--early` | rights | Post-trim rights pass for clip-heavy formats (react, news, documentary) |
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
