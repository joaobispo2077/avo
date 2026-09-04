# /avo.help Command

**Timeline integration:** Admin

## Workflow guidance

**Workflow steps:** Validate help prerequisites → Run help → Verify and report the help result
**Step state source:** the observed invocation result and any command-owned manifest
**Stopping conditions:** Missing required input, a failed or stale gate, a required human decision, or verified help completion
**Valid next commands:** the selected /avo.* command

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

Master index of all `/avo.*` slash commands. Spoken alias: **`/avo --help`**.

**Skill:** [`agent-skills/avo-pipeline/references/help.md`](../../agent-skills/avo-pipeline/references/help.md)

---

## Usage

```
/avo.help
```

Optional: `--section pipeline|guidelines|ops|docs`

---

## Role

Discovery only. Does not run pipeline stages. Print the command catalog and point to the right slice.

---

## Instructions

1. Load [`help.md`](../../agent-skills/avo-pipeline/references/help.md).
2. If `--section` set, print that group only; else print full index.
3. Remind: declare **Provider** + **footage location** (path or “this folder”) before any executing command.
4. Link [`docs/avo-commands.md`](../../docs/avo-commands.md) for copy-paste examples.

## Shared timeline gateway

Resolves provider/video context but performs no editorial timeline mutation. Reports and configuration reference canonical artifact/revision identities.
