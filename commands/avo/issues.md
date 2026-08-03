# /avo.issues Command

Prepare a GitHub issue with full environment context — user submits manually.

**Skill:** [`agent-skills/avo-pipeline/references/issues.md`](../../agent-skills/avo-pipeline/references/issues.md)

---

## Usage

```
/avo.issues
type: bug
```

Types: `bug` · `docs` · `enhancement` · `resources` · `other`

---

## Role

Read-only preparation. Gathers reproducible context and formats a markdown body for the matching GitHub issue form. Does **not** auto-submit unless the user explicitly requests `gh issue create` and is authenticated.

---

## Instructions

1. Ask which issue type (or infer from user description).
2. Collect: OS, agent product, AVO version (`git describe --tags` from repo root), provider slug (if any), stage/slash command, repro steps, expected vs actual.
3. **Never** paste secrets, `.env`, or private footage paths without explicit user confirmation.
4. Output:
   - Formatted markdown body ready to paste
   - Issue chooser URL: `https://github.com/joaobispo2077/avo/issues/new/choose`
5. Note: **GitHub account required** to file. Issues from sponsors **may be prioritized** in the investigation queue (manual policy, not automated).
6. Offer to open the chooser URL or run `gh issue create` only if user explicitly asks.

---

## Example

```text
/avo.issues
type: bug
```
