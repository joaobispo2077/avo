# Contract: AVO Step-Status Responses

## Scope

Applies to AVO-owned entry skills, the AVO pipeline/provider skills, every `/avo.*` command prompt, their progress messages, approval/input prompts, blocker reports, and completion responses. It does not rewrite unrelated third-party skills or general conversation.

## Required final block

Every user-facing AVO response ends with exactly one block in this form:

```markdown
**Workflow:** `/avo.<command>`
**Current step:** `<declared user-facing step>` — `<not started | in progress | awaiting user | blocked | completed>`
**Next step:** `<next declared step | Workflow complete>`
**Next expected update:** `<what the agent will report next, or the exact user action that triggers it>`
```

No content follows the block. The result, warning, question, or blocker appears before it.

## Command prompt metadata

Every `commands/avo/*.md` wrapper declares exactly once:

```markdown
## Workflow guidance

**Workflow steps:** `<ordered user-facing stages>`
**Step state source:** `<durable artifact or observed invocation result>`
**Stopping conditions:** `<gates, blockers, completion>`
**Valid next commands:** `<allowed /avo.* commands>`

Follow the shared step-status response contract.
```

Routed references may provide more detailed state mappings, but may not contradict the wrapper.

## State authority

Use, in order of relevance:

1. `pipeline-run.json` main/side state;
2. current `review.json` and approval record;
3. `shorts.status.json` batch/item state;
4. `delivery-manifest.json` preparation/delivery state;
5. observed result for a one-shot command.

If durable state exists, conversation memory cannot override it. `needs-human-judgment` or AI-passed without approval maps to `awaiting user`; `blocked`, stale, or superseded state maps to `blocked`; delivered/archived or one-shot success maps to `completed`.

## Input and approval prompts

Before the final block, state:

- why the input is needed;
- what decision/artifact it controls;
- the exact acceptable reply or choices;
- any material tradeoff or safety consequence.

`Next expected update` states what the agent will do after that exact reply.

## Blocked and completed responses

A blocked response identifies the failed prerequisite and evidence, provides the minimum unblocking action, and does not imply later gates passed. A completion response summarizes verified outputs and names a valid next command or says the workflow is complete.

## Static enforcement

Tests scan all shipped wrappers and the `avo`, `avo-pipeline`, and `avo-provider` entry skills for the shared contract. Example tests cover start, progress, approval, blocked, and completion responses and assert the block is last.
