# /avo.issues reference

Agent-guided GitHub issue preparation. User submits manually on GitHub.

## When to use

- Before filing a bug, docs fix, enhancement, or creator showcase request
- When the user needs help gathering OS, agent, version, provider, and repro context

## Issue chooser

```text
https://github.com/joaobispo2077/avo/issues/new/choose
```

Templates live in `.github/ISSUE_TEMPLATE/`:

| Type | Template file |
| ---- | ------------- |
| Bug | `bug_report.yml` |
| Documentation | `documentation.yml` |
| Enhancement | `enhancement.yml` |
| Third-party resources | `third_party_resources.yml` |
| Other (creators, sponsorship) | `other_request.yml` |

Security: use GitHub private vulnerability reporting — link in `config.yml` contact_links, **not** the public bug form.

## Agent workflow

1. **Confirm type** — bug, docs, enhancement, resources, other.
2. **Collect environment** (ask; do not invent):
   - OS (Windows / macOS / Linux / WSL)
   - Agent product (Cursor, Claude Code, Codex, …)
   - AVO version: `git describe --tags` from AVO repo root
   - Provider slug if footage-related (or `none`)
   - Slash command or stage (`/avo.trim`, install, …)
3. **Repro** — numbered steps, expected vs actual, redacted logs.
4. **Secrets** — never include `.env`, API keys, or private paths without explicit user OK.
5. **Output** — markdown body matching the template fields + chooser URL.
6. **Submission** — user pastes into GitHub. Auto-submit via `gh issue create` **only** when user explicitly requests and `gh auth status` succeeds.

## Sponsor note (copy for bug/enhancement bodies)

> Issues from GitHub Sponsors or Buy Me a Coffee supporters may be prioritized in the investigation queue when feasible. This is a manual maintainer policy — not automated tiering and not a paywall on core features.

## Related

- [`supporters.md`](supporters.md) — sponsor links and backlog policy
- [`docs/ROADMAP.md`](../../docs/ROADMAP.md) — public backlog
