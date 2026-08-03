# Video work modes — parallelism and concurrency

AVO supports multiple videos per provider. Two **work modes** define how you (and the agent) manage context across videos.

## Parallelism mode (recommended)

**One Cursor chat per video.**

```text
Provider: bishop
Video: 20260803-explainer
```

Each chat declares `Provider` + `Video` once at session start. Config isolation comes from:

1. External `<rawDir>/avo.project.json` (per-video overrides)
2. Per-video runtime state in `.avo/state.json` under `videos["provider:videoId"]`
3. Separate chat context (no shared `.avo/active-context.json`)

You can change global `avo.config.json` while another video runs in a different chat — in-flight videos keep their project + scoped state.

**Do not** use `python -m avo.videos context set` in parallelism mode; it is for concurrency only.

## Concurrency mode (supported, discouraged)

**Same chat, multiple videos** — only when you always declare which video is active.

Before every `/avo.*` command:

```text
Video: 20260803-explainer
```

Set active context once per switch:

```bash
python -m avo.videos context set --provider bishop --video-id 20260803-explainer
python -m avo.videos context show
python -m avo.videos context clear
```

The agent should warn if you switch videos without an explicit declaration. Concurrency is harder to reason about and easier to confuse paths or models.

## Decision table

| Situation | Use |
|-----------|-----|
| Multiple videos, normal workflow | **Parallelism** — one chat per video |
| Strong machine, experienced user, same chat | **Concurrency** — declare `Video:` every turn |
| Weak hardware / long renders | **Parallelism** only |
| Changing global config mid-flight | Safe with parallelism + per-video `avo.project.json` |

## Advisory locks

Optional warn-only lock when two agents might touch the same footage:

```bash
python -m avo.videos lock acquire --provider bishop --video-id 20260803-explainer
python -m avo.videos lock status --raw-dir D:/footage/explainer-01
python -m avo.videos lock release --raw-dir D:/footage/explainer-01
```

Lock file: `<rawDir>/edit/.avo-lock.json`. Advisory only — never blocks.

## Config resolution order

```text
avo.config.json                    ← global defaults
providers/<slug>/avo.provider.json ← brand + provider defaults
providers/<slug>/videos/<id>/video.json defaults  ← bootstrap hints (optional)
<rawDir>/avo.project.json          ← runtime overrides (highest for project fields)
.avo/state.json videos[key]        ← session model picks when video context is set
```

## CLI quick reference

```bash
python -m avo.videos list --provider bishop
python -m avo.videos resolve --provider bishop --video-id 20260803-explainer --verbose
python -m avo.videos context set --provider bishop --video-id 20260803-explainer
python -m avo.stats show --provider bishop --video-id 20260803-explainer
```

See also: [providers.md](providers.md), [agent-skills/avo-pipeline/references/arguments.md](../agent-skills/avo-pipeline/references/arguments.md).
