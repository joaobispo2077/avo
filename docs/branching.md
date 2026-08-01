# Branching policy

---

## User owns branches

The **user** decides which branch to use. Agents:

- Work **only** on the currently checked-out branch
- **Never** create, delete, rename, checkout, switch, merge, or orchestrate branches
- **Never** push unless explicitly requested

Agents may **infer context** from the branch name (ticket, scope) for specs and changelog
entries.

---

## Expected branch patterns

| Pattern | Example | Agent use |
| ------- | ------- | --------- |
| `feature/${ticket}` | `feature/GTW-233` | Link ticket in `CHANGELOG.md` |
| `feature/${scope}` | `feature/avo-install` | Link `./docs/${scope}.md` in changelog |
| `main` | default trunk | release target |

### Ticket branches

When the branch contains a ticket id (e.g. `GTW-233`), reference it in changelog items:

```md
- Add install slug canonicalization [GTW-233](https://aircanada.atlassian.net/servicedesk/customer/portal/1670/GTW-233)
```

Replace the URL base if your org uses a different tracker.

### Scope branches (no ticket)

When the branch is `feature/dynatrace`, extract scope `dynatrace`:

1. Create or update `./docs/dynatrace.md` with what was done
2. Reference in changelog: `[dynatrace](./docs/dynatrace.md)`

---

## AVO launch note

Pre-launch work may live on `main` or a long-lived feature branch until
`joaobispo2077/avo` is published. Agents do not change remotes or push without
explicit user request.
