# /avo.watch Command

Full watch-skill LOOP review and audit of the current proof scope.

**Skill:** [`docs/avo-pipeline/references/watch.md`](../../docs/avo-pipeline/references/watch.md)

---

## Usage

```
/avo.watch
Provider: my-channel
rawDir: /path/to/footage
```

Optional: `Proof: edit/preview/edit-proof.mp4` (default: latest proof in `edit/preview/`)

---

## Role

Run stage 3 (understand / verify): watch-skill inspect → agent fixes → re-check until confidence holds. Prepare human approval package.

---

## Instructions

1. Resolve latest proof MP4 under `edit/preview/` (edit-proof or motion-proof).
2. Invoke **watch-skill** (MCP/CLI/REST) with stage intent + acceptance criteria.
3. Summarize defects in plain language; apply fixes via owning tool; re-run LOOP.
4. Write `edit/review/<checkpoint>/approval-gate.md` listing preview + review paths.
5. **Stop and wait** for explicit user approval before promotion or next stage.

High confidence from watch-skill does **not** replace human sign-off.

---

## Example

```text
/avo.watch
Provider: my-channel
rawDir: H:/footage/ep-03
Proof: edit/preview/motion-proof.mp4
```
