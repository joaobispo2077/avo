---
applyTo: "**"
---

# Versioning and Documentation Instructions

## SemVer (orchestrator software)

- Version: `MAJOR.MINOR.PATCH` · Tags: `vMAJOR.MINOR.PATCH` (annotated)
- Changelog: `CHANGELOG.md`
- Update changelog **only** when user confirms task is 100% finished
- Recommend tag commands; **never** create/push tags unless explicitly asked

```bash
git tag -a v0.2.0 <commit-sha> -m "v0.2.0"
git push origin v0.2.0
```

## Video exports (separate)

Footage exports use `YYYYMMDD-video-slug-stage-v001` — not in `CHANGELOG.md`.

## Branch → changelog

- Ticket in branch (`feature/GTW-233`): link ticket in changelog entry
- Scope only (`feature/avo-install`): create/update `docs/avo-install.md`, link from changelog

See `docs/branching.md` and `docs/versioning.md`.

## Documentation policy

- User-requested behavior, decisions, comparisons, strategies → `./docs/*.md`
- kebab-case filenames; practical and accurate
- Link from changelog when no ticket reference

## Branches

Agents never switch or create branches. User owns branch orchestration.
