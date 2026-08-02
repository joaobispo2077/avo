# /avo.update Command

Refresh your AVO install from GitHub — new features, updated agent skills, and toolchain — **without losing the providers you already set up** (e.g. `bishop`).

**Skill:** [`agent-skills/avo-pipeline/references/update.md`](../../agent-skills/avo-pipeline/references/update.md)

---

## Usage (you say this)

```
/avo.update
/avo.update check
/avo.update yes
```

No terminal commands required unless you prefer manual control.

---

## Role

**For people using AVO in their agent** (Cursor, Claude Code, Codex, …) — not for contributing to the AVO repo itself.

Run every few weeks when you want the latest `/avo.*` commands, skills, and fixes. Your provider workspaces (`providers/<slug>/` — brand, manifest, learndowns) must survive unchanged.

---

## Instructions (agent executes — do not ask the user to run npm/git)

1. **Locate the user's AVO install root** — the folder where they installed AVO and created providers (usually the workspace root if this project is open, or the path from initial `/avo.provider` / setup).
2. **Optional check** — when the user says `check` or has not asked to apply yet:
   - Run `python -m avo.update check` from that root (agent runs it; user does not).
   - Report in plain language: up to date or N commits behind, current version, provider slugs found.
3. **Apply** — when the user confirms or says `yes`:
   - Run `python -m avo.update apply --yes` from the AVO install root.
   - This pulls latest AVO (fast-forward only), refreshes **all agent skills + slash commands**, runs a **full toolchain refresh** (Python engine, ffmpeg path, watch-skill, HyperFrames), and verifies every provider still exists.
4. **Report to the user:**
   - Before/after version (from `package.json`)
   - Provider list unchanged (e.g. `bishop` ✓)
   - What was refreshed (skills, toolchain)
   - Ask them to **start a new agent chat** or reload so updated skills/commands load
5. **Do not** tell the user to run `npm run update`, `git pull`, or `python -m …` unless they explicitly ask for manual steps.

### If update is blocked

| Situation | Tell the user |
| --- | --- |
| Dirty tracked files in AVO folder | Commit or stash repo changes, then retry `/avo.update yes` |
| Offline / fetch failed | Try again when online |
| No git clone (Tier 1 curl-only install) | Re-run the README install one-liner; providers in a clone are preserved separately — see skill reference |
| Provider missing after update | **Stop** — do not continue editing; report which slug failed |

---

## Provider preservation (release-blocking)

Before any pull or sync, snapshot every `providers/<slug>/` with a valid `avo.provider.json`. After sync, verify the same slugs and manifests exist. If any provider is missing, report failure — the user's channel config must not be silently lost.

Provider folders are gitignored; a normal update never deletes them. The verify step catches regressions.

---

## Example

```text
/avo.update
```

Agent: "You're 12 commits behind. Providers: bishop. Pull and full refresh?"

```text
/avo.update yes
```

Agent: "Updated to 1.0.2. bishop provider OK. Skills and toolchain refreshed. Start a new chat to pick up new commands."

---

## Related

- First install: README § Install
- Create a provider: `/avo.provider`
- Advisory background check (agents only): weekly `check-update` — lightweight, not a substitute for `/avo.update`
