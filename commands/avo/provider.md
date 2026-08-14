# /avo.provider Command

**Timeline integration:** Owns

Configure or create an AVO **provider** — publishing destination, brand, palette,
manifest metadata, and scope.

**Skill:** [`agent-skills/avo-provider/SKILL.md`](../../agent-skills/avo-provider/SKILL.md)  
**Concept doc:** [`docs/providers.md`](../../docs/providers.md)

---

## Usage

```
/avo.provider
/avo.provider create <slug>
/avo.provider audit <slug>
/avo.provider explain
```

---

## Role

Provider setup only. Does not transcribe, cut, or render. Outputs a configured
`providers/<slug>/` workspace and a disclosure summary for user confirmation.

---

## Instructions

1. Load [`agent-skills/avo-provider/SKILL.md`](../../agent-skills/avo-provider/SKILL.md).
2. If `explain` — summarize [`docs/providers.md`](../../docs/providers.md) for the user.
3. If `create` — run diagnosis (platform, slug, scope, split vs merge), then scaffolder + brand files.
4. If `audit` — read existing manifest, DESIGN.md, palette; report gaps vs checklist.
5. Never commit media; never set `rawRoot` inside the AVO repo.

## Animation library integration

Configures the optional provider animation catalog pointer and performs only explicit creator-authorized sanitized promotion. Video or chapter approval never promotes a pattern.

## Shared timeline gateway

Uses shared timeline storage, transition guards, invalidation, and AI review services. It cannot maintain private CMap, BMap, sync, track, animation, or approval truth.
