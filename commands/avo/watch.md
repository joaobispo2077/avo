# /avo.watch Command

**Timeline integration:** Evidence

Full watch-skill LOOP review and audit of the current proof scope.

**Skill:** [`agent-skills/avo-pipeline/references/watch.md`](../../agent-skills/avo-pipeline/references/watch.md)

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

## Shared review front end

`/avo.watch` invokes the candidate-bound review orchestrator; it is not a
standalone prose review. Every evidence item records tool/version, run time,
exact candidate SHA-256, dependency hashes, scope/coverage, findings, fixes, and
artifacts in `edit/review/<checkpoint>/review.json`. Full-program review is
preferred; targeted review must include every changed/risk window and is never
labeled full. A tool outage produces `blocked`, not a waiver.

## Shared timeline gateway

Runs shared candidate-bound checks and emits evidence with exact candidate/dependency hashes. Scoped evidence cannot satisfy a larger gate without required coverage.
