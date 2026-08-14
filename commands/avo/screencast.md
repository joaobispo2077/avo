# /avo.screencast Command

**Timeline integration:** Profile

Screencast / tutorial technique router (oversized cursor house style).

**Skill:** [`agent-skills/avo-pipeline/references/screencast.md`](../../agent-skills/avo-pipeline/references/screencast.md)

---

## Usage

```
/avo.screencast
Provider: my-channel
ProjectDir: /path/to/project
Source: /path/to/screencast-footage
```

---

## Instructions

1. Parse `Provider`, `ProjectDir`, `Source` (footage path or screen recording folder).
2. Follow [`screencast.md`](../../agent-skills/avo-pipeline/references/screencast.md).

## Shared timeline gateway

Runs the base pipeline with format-specific diagnosis and policy. It creates its own timeline context for derivatives and cannot bypass lineage, invalidation, Watch, transcript, or approval gates.
