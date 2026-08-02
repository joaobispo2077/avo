# /avo.docs Command

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
