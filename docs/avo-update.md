# AVO update (`/avo.update`)

End-user command to refresh an AVO install from GitHub — new `/avo.*` skills, orchestrator fixes, and toolchain — **without losing provider workspaces** under `providers/<slug>/`.

## Who this is for

People **using AVO in an agent** (Cursor, Claude Code, Codex, …) to edit videos. Not for contributors hacking the AVO repo (they use normal git).

## What you say

```text
/avo.update
/avo.update check
/avo.update yes
```

Your agent runs everything. You should not need npm, git, or Python commands unless you want manual control.

## What happens

| Step | Agent runs (you don't) | Purpose |
| --- | --- | --- |
| Check | `python -m avo.update check` | Compare local vs GitHub; list providers |
| Apply | `python -m avo.update apply --yes` | Pull (ff-only), refresh skills + toolchain |
| Verify | Built into apply | Same provider slugs + manifests as before |

After a successful apply, **start a new agent chat** so updated skills and slash commands load.

## Provider preservation (release-blocking)

Gitignored folders like `providers/bishop/` hold your channel brand, manifest, and learndowns. Update:

1. Snapshots every `providers/<slug>/` with a valid `avo.provider.json` before pull/sync
2. Verifies the same slugs exist after sync
3. **Fails** if any provider or manifest is missing — your channel config must not be silently lost

## Blocked states

| Situation | What to do |
| --- | --- |
| Uncommitted changes in the AVO folder | Commit or stash tracked files, then `/avo.update yes` |
| Offline / fetch failed | Retry when online |
| Not a git clone (Tier 1 curl install) | Re-run the README install one-liner; use a clone + `/avo.provider` for provider workspaces |
| Provider missing after update | Stop editing; report failure to support — do not continue pipeline work |

## Install models

| Install | `/avo.update` |
| --- | --- |
| **Recommended:** clone + `--full` setup, AVO as workspace | Full check → pull → skills → toolchain → verify |
| Tier 1 curl-only (skills only) | No git pull — re-run README installer; providers need a clone |

## Advisory vs full update

- **Weekly check** (agents, session start): lightweight “N commits behind” nudge → suggests `/avo.update`
- **`/avo.update`**: full refresh including skills reinstall and toolchain setup

## Manual / troubleshooting

From an AVO clone (advanced only):

```bash
npm run update -- check
npm run update -- apply --yes
npm run update -- apply --yes --dry-run
```

## Related

- Command: [`commands/avo/update.md`](../commands/avo/update.md)
- Skill reference: [`agent-skills/avo-pipeline/references/update.md`](../agent-skills/avo-pipeline/references/update.md)
- Install: [`docs/install/README.md`](install/README.md#updating-your-install)
