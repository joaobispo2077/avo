# /avo.supporters reference

## Step/state mapping

**Durable state:** the observed invocation result and any command-owned manifest

**Workflow steps:** Validate supporters prerequisites → Run supporters → Verify and report the supporters result

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing required input, a failed or stale gate, a required human decision, or verified supporters completion

**Valid next commands:** /avo.issues or /avo.help

Read-only sponsorship and prioritization surface.

## When to use

- User asks how to fund AVO or move roadmap items up
- After `/avo.issues` when sponsor interest applies

## Links (canonical)

From [`.github/FUNDING.yml`](../../../.github/FUNDING.yml):

- **GitHub Sponsors:** [github.com/sponsors/joaobispo2077](https://github.com/sponsors/joaobispo2077)
- **Buy Me a Coffee:** [buymeacoffee.com/joaobispo2077](https://buymeacoffee.com/joaobispo2077)

## Prioritization policy (prose for agents)

AVO is free and open source. Sponsorship helps the maintainer allocate time to **roadmap** capabilities (see [`docs/ROADMAP.md`](../../docs/ROADMAP.md)) — upscaling, locale packs, voice profiles, library workflows, NLE export, and similar.

- **Core pipeline commands stay free.** Sponsorship does not gate install, transcribe, trim, deliver, or provider setup.
- **Queue priority is manual.** Sponsors who file issues may receive faster triage when feasible; there is no automated SLA.
- **Signal sponsor interest** via the optional checkbox on bug/enhancement issue templates, or mention sponsorship in the issue body.

## Related

- [`issues.md`](issues.md) — structured issue filing
- [`creators.md`](creators.md) — public showcase list
