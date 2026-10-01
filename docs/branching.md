# Branching policy

---

## User owns branches

The **user** decides which branch to use. Agents:

- Work **only** on the currently checked-out branch
- **Never** create, delete, rename, checkout, switch, merge, or orchestrate branches
- **Never** push unless explicitly requested
- If a pull request head has the wrong name, ask the user to rename it. Do not create a replacement branch.

Agents may **infer context** from the branch name (ticket, scope) for specs and changelog
entries.

---

## Branch name pattern

`feature/{project_name}-{VARIABLE}`

- `{project_name}` is the repository slug. In this repo it is `avo`.
- `{VARIABLE}` is the work slug (for example `bot-avatars`) or an issue id (for example `issue-5`).

Examples:

- `feature/avo-bot-avatars`
- `feature/avo-issue-5`

---

## Merge order

When `develop` (or `dev`) and `release` exist, merge in this order only:

1. `feature/…` → `develop` / `dev`
2. `develop` / `dev` → `release`
3. `release` → `main` / `master`

Do not open a feature pull request straight to `main` or `master` while `develop`/`dev` and `release` exist.

`joaobispo2077/avo` has `develop` and `release`. Feature work targets `develop`.

---

## Changelog links

### Issue branches

When `{VARIABLE}` contains an issue id (for example `feature/avo-issue-5`), reference it in changelog items.

### Scope branches (no issue)

When the branch is `feature/avo-install`, the scope is `avo-install`:

1. Create or update `./docs/avo-install.md` with what was done
2. Reference in changelog: `[avo-install](./docs/avo-install.md)`

---

## AVO launch note

`develop` and `release` exist on `joaobispo2077/avo`. Feature pull requests target `develop`, then follow the merge order above. Agents do not change remotes or push without an explicit user request.
