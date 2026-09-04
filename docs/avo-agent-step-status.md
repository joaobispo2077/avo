# AVO agent step status

Every AVO command now reports where the user is in the active workflow. The
shared contract lives in
[`agent-skills/avo-pipeline/references/step-status.md`](../agent-skills/avo-pipeline/references/step-status.md).
Command wrappers declare the ordered workflow, durable state source, stopping
conditions, and valid next commands; routed references refine those declarations
without inventing a separate workflow.

## Response contract

Every progress update, input request, blocker, resumed run, and completion
response ends with exactly one four-line block:

```markdown
**Workflow:** `/avo.<command>`
**Current step:** `<declared step>` — `<not started | in progress | awaiting user | blocked | completed>`
**Next step:** `<declared next step | Workflow complete>`
**Next expected update:** `<next report or exact user action>`
```

Nothing follows the block. The useful result, warning, question, or evidence
comes before it.

## State and resume behavior

Durable project state is authoritative. Resolve it in this order when the
artifacts apply: `pipeline-run.json`, `review.json`, `shorts.status.json`,
`delivery-manifest.json`, then the observed result of a one-shot invocation.
Re-read state after a resume or approval and immediately before claiming
completion. Conversation history may explain intent but cannot advance durable
state.

An approval prompt states why the answer is required, what it controls, the
exact accepted reply, and its safety or workflow consequence. A blocker names
the failed prerequisite, evidence, minimum unblocking action, and confirms that
later gates were not evaluated. Completion lists verified outputs and a valid
next command, or says `Workflow complete`.

## Prompt-authoring example

```markdown
## Workflow guidance

**Workflow steps:** Validate inputs → Build proof → Review proof
**Step state source:** current review.json and candidate-bound evidence
**Stopping conditions:** Missing input, stale evidence, human decision, or verified completion
**Valid next commands:** /avo.watch or /avo.deliver

Follow the shared step-status response contract for every user-facing response.
```

Use user-facing step names. Internal functions, retries, or implementation
phases do not belong in the footer unless they are themselves meaningful user
steps.
