# /avo.general Command

**Timeline integration:** Profile

Router to custom HyperFrames composition skill.

**Skill:** [`agent-skills/avo-pipeline/references/general.md`](../../agent-skills/avo-pipeline/references/general.md)

---

## Usage

```
/avo.general
Provider: my-channel
ProjectDir: /path/to/project
Source: /path/to/composition-brief.md
```

---

## Instructions

1. Parse `Provider`, `ProjectDir`, `Source` (brief, spec, or storyboard path).
2. Follow [`general.md`](../../agent-skills/avo-pipeline/references/general.md).

## Shared timeline gateway

Runs the base pipeline with format-specific diagnosis and policy. It creates its own timeline context for derivatives and cannot bypass lineage, invalidation, Watch, transcript, or approval gates.
