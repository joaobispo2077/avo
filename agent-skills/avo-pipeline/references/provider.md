# /avo.provider reference

## Step/state mapping

**Durable state:** the resolved provider avo.provider.json manifest

**Workflow steps:** Validate provider prerequisites → Run provider → Verify and report the provider result

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing required input, a failed or stale gate, a required human decision, or verified provider completion

**Valid next commands:** /avo.pipeline

Implements provider setup via skill **`avo-provider`**.

## Canonical docs

- [`docs/providers.md`](../../providers.md) — what a provider is
- [`providers/README.md`](../../../providers/README.md) — directory layout
- [`agent-skills/avo-provider/SKILL.md`](../../../agent-skills/avo-provider/SKILL.md) — agent workflow

## Commands

| Intent | Action |
| --- | --- |
| Explain concept | Summarize `docs/providers.md` |
| Create provider | `python -m avo.provider_scaffold`, then edit manifest + DESIGN + palette |
| Audit provider | Validate manifest vs schema; check brand file sync |
| First video | `python -m avo.init_project --provider <slug> --raw-dir <path>` |

## Multi-provider reminder

Prefer **one provider per platform/format**. Same channel may use separate slugs
for long-form vs Shorts — see
[`agent-skills/avo-provider/references/multi-provider-patterns.md`](../../../agent-skills/avo-provider/references/multi-provider-patterns.md).

## Animation library integration

Provider animation catalogs contain only explicitly creator-approved generalized behavior. Strip project text, timestamps, claims, screenshots, footage, and restricted media. Store contexts, exclusions, required assets, accessibility, compatible formats, exemplar hashes, and promotion provenance. Diagnose the new video first; recommend but never force. Every reuse gets fresh timing, layout, face/caption/evidence, rights, and accessibility review.
