# /avo.provider reference

Implements provider setup via skill **`avo-provider`**.

## Canonical docs

- [`docs/providers.md`](../../providers.md) — what a provider is
- [`providers/README.md`](../../../providers/README.md) — directory layout
- [`agent-skills/avo-provider/SKILL.md`](../../../agent-skills/avo-provider/SKILL.md) — agent workflow

## Commands

| Intent | Action |
| --- | --- |
| Explain concept | Summarize `docs/providers.md` |
| Create provider | `scripts/new-provider.sh` / `new-provider.ps1`, then edit manifest + DESIGN + palette |
| Audit provider | Validate manifest vs schema; check brand file sync |
| First video | `python -m avo.init_project --provider <slug> --raw-dir <path>` |

## Multi-provider reminder

Prefer **one provider per platform/format**. Same channel may use separate slugs
for long-form vs Shorts — see
[`agent-skills/avo-provider/references/multi-provider-patterns.md`](../../../agent-skills/avo-provider/references/multi-provider-patterns.md).
