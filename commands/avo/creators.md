# /avo.creators Command

**Timeline integration:** Admin

## Workflow guidance

**Workflow steps:** Validate creators prerequisites → Run creators → Verify and report the creators result
**Step state source:** the observed invocation result and any command-owned manifest
**Stopping conditions:** Missing required input, a failed or stale gate, a required human decision, or verified creators completion
**Valid next commands:** /avo.help

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

Curated opt-in list of channels and sites using AVO.

**Skill:** [`agent-skills/avo-pipeline/references/creators.md`](../../agent-skills/avo-pipeline/references/creators.md)

---

## Usage

```
/avo.creators
```

---

## Role

Read-only showcase. Lists maintainer-curated entries from `docs/creators.md`. No scraping.

---

## Instructions

1. Read [`docs/creators.md`](../../docs/creators.md) and summarize current entries.
2. For submissions: direct user to GitHub **Other request** issue template (category: Creator showcase) with name, platform, public URL, opt-in confirmation.
3. Do not add entries without maintainer merge.

---

## Example

```text
/avo.creators
```

## Shared timeline gateway

Resolves provider/video context but performs no editorial timeline mutation. Reports and configuration reference canonical artifact/revision identities.
