# /avo.docs Command

**Timeline integration:** Admin

## Workflow guidance

**Workflow steps:** Validate docs prerequisites → Run docs → Verify and report the docs result
**Step state source:** the observed invocation result and any command-owned manifest
**Stopping conditions:** Missing required input, a failed or stale gate, a required human decision, or verified docs completion
**Valid next commands:** /avo.help

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

Route to AVO topic documentation.

**Skill:** [`agent-skills/avo-pipeline/references/docs.md`](../../agent-skills/avo-pipeline/references/docs.md)

---

## Usage

```
/avo.docs
topic: workflow
```

Topics: `workflow` · `commands` · `install` · `audio` · `animation` · `delivery` · `use-cases` · `index`

---

## Role

Doc discovery. Opens the right markdown file; does not execute pipeline.

---

## Instructions

1. Parse `topic` (default: `index`).
2. Load path from docs router table in [`docs.md`](../../agent-skills/avo-pipeline/references/docs.md).
3. Summarize what the doc covers in 3–5 bullets; offer to proceed with a matching `/avo.*` command.

---

## Example

```text
/avo.docs
topic: workflow
```

## Shared timeline gateway

Resolves provider/video context but performs no editorial timeline mutation. Reports and configuration reference canonical artifact/revision identities.
