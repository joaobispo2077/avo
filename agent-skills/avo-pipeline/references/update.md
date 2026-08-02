# /avo.update reference

**Audience:** end users running AVO inside an agent — YouTube creators, editors, not AVO repo contributors.

## When the user should run it

- ~2–4 weeks after install or last update
- New `/avo.*` commands or features they want
- Before a new video project on an stale install

## What the user says

```
/avo.update
/avo.update check
/avo.update yes
```

They should **not** need to open a terminal or know git/npm.

## What the agent does (REQUIRED)

1. Resolve **AVO install root** — workspace root when this repo is open, or path from prior setup / `avo.provider` / `.avo/state.json` context.
2. **Check** (optional): `python -m avo.update check` — report behind/ahead, version, providers in plain language.
3. **Apply** (after confirm or `yes`): `python -m avo.update apply --yes`
4. Summarize results: version, providers preserved, skills + toolchain refreshed.
5. Remind user to **reload agent** (new chat / restart) so updated skills and `/avo.*` commands load.

**Do not** paste npm/git commands to the user unless they ask for manual control.

## What full refresh includes (agent runs; user doesn't)

| Step | Purpose |
| --- | --- |
| `git fetch` + `git pull --ff-only` | Latest orchestrator code |
| `node bin/install.cjs --yes` | Refresh `avo`, `avo-pipeline`, `avo-provider` skills + Cursor `/avo.*` commands |
| `scripts/setup.sh --yes --lang <stored>` | Full Tier 2 toolchain (engine, whisper, watch-skill, HyperFrames) |

Language comes from `.avo/state.json` (`transcription.language`), default `en`.

## Provider preservation (release-blocking)

Snapshot `providers/<slug>/` (with `avo.provider.json`) before update. Verify identical set after sync. Missing slug or manifest → report failure; user must not lose channel config (e.g. `bishop`).

Gitignored provider dirs are never deleted by git pull.

## Install models

| How they installed | `/avo.update` behavior |
| --- | --- |
| **Recommended:** clone + `--full` setup, AVO as workspace | Full check → pull → skills → toolchain → verify providers |
| Tier 1 curl-only (skills only, no clone) | No git pull possible — agent re-runs README install one-liner (`curl … install.sh` or `npx skills add …`). Providers live in a clone; if they never cloned, point them to clone + `/avo.provider` first |

## Agent phrasing (examples)

- Check: "You're on AVO 1.0.1. GitHub has 8 new commits. Providers: bishop. Say `/avo.update yes` to upgrade."
- Success: "Updated to 1.0.2. bishop unchanged. Skills and toolchain refreshed. Start a new chat."
- Blocked: "Can't update — you have uncommitted changes in the AVO folder. Commit or stash, then retry."

## Flags (agent use only)

| Internal flag | When |
| --- | --- |
| `check` | Compare only |
| `apply --yes` | Pull + full sync |
| `--dry-run` | Explain plan without changes |
| `--json` | Machine-readable report for logs |

See [`commands/avo/update.md`](../../../commands/avo/update.md).
