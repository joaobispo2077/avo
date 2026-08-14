# /avo.explainer Command

**Timeline integration:** Profile

Router to faceless explainer / article → video skill.

**Skill:** [`agent-skills/avo-pipeline/references/explainer.md`](../../agent-skills/avo-pipeline/references/explainer.md)

---

## Usage

```
/avo.explainer
Provider: my-channel
ProjectDir: /path/to/explainer-project
Source: /path/to/article.md
```

---

## Instructions

1. Parse `Provider`, `ProjectDir`, `Source` (article, notes, or topic file).
2. Follow [`explainer.md`](../../agent-skills/avo-pipeline/references/explainer.md).

## Shared timeline gateway

Runs the base pipeline with format-specific diagnosis and policy. It creates its own timeline context for derivatives and cannot bypass lineage, invalidation, Watch, transcript, or approval gates.
