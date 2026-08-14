# /avo.launch Command

**Timeline integration:** Profile

Router to product / marketing launch video skill.

**Skill:** [`agent-skills/avo-pipeline/references/launch.md`](../../agent-skills/avo-pipeline/references/launch.md)

---

## Usage

```
/avo.launch
Provider: my-channel
ProjectDir: /path/to/launch-project
Source: https://example.com/product
```

---

## Instructions

1. Parse `Provider`, `ProjectDir`, `Source` (product URL, marketing page, or pasted brief path).
2. Follow [`launch.md`](../../agent-skills/avo-pipeline/references/launch.md).

## Shared timeline gateway

Runs the base pipeline with format-specific diagnosis and policy. It creates its own timeline context for derivatives and cannot bypass lineage, invalidation, Watch, transcript, or approval gates.
