# /avo.watch Command

**Timeline integration:** Evidence

## Workflow guidance

**Workflow steps:** Validate watch prerequisites → Run watch → Verify and report the watch result
**Step state source:** current review.json and approval record
**Stopping conditions:** Missing required input, a failed or stale gate, a required human decision, or verified watch completion
**Valid next commands:** the declared human approval gate

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

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

Inspect the effective execution policy with `avo review policy --project
<avo.project.json>`. One-run controls are `--watch-whisper-model`,
`--watch-device`, `--watch-max-frames`, `--watch-repair-max-frames`,
`--watch-analysis-attempts`, `--watch-tool-attempts`,
`--watch-working-directory`, `--watch-format`, `--watch-language`, repeatable
`--watch-acceptance-criterion`, and repeatable `--watch-risk-note`. Full values,
precedence, failure behavior, and next actions are in
[`docs/optional-capabilities.md`](../../docs/optional-capabilities.md).

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
