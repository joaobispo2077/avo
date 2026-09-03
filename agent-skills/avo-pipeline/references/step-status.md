# AVO step-status response contract

Load this contract for every AVO-owned entry skill, `/avo.*` command, progress
message, approval or input prompt, blocker report, resume, and completion
response. It does not apply to unrelated third-party skills or general
conversation.

## Required final block

End every user-facing AVO response with exactly one concise block. No content
may follow it.

```markdown
**Workflow:** `/avo.<command>`
**Current step:** `<declared user-facing step>` — `<status>`
**Next step:** `<next declared step | Workflow complete>`
**Next expected update:** `<what the agent will report next, or the exact user action that triggers it>`
```

**Allowed statuses:** `not started` | `in progress` | `awaiting user` | `blocked` | `completed`

Lead with the result, warning, question, or blocker. The footer is orientation,
not a substitute for reporting evidence. Keep it to these four lines even for a
long workflow.

## State authority and resume behavior

Resolve current state from the most specific durable source available, in this
order:

1. `pipeline-run.json` main or side state;
2. current `review.json` and approval record;
3. `shorts.status.json` batch or item state;
4. `delivery-manifest.json` preparation or delivery state;
5. observed invocation result for a one-shot command.

If durable state exists, conversation memory cannot override it. Read durable
Read durable state again when a workflow resumes, after an approval, and before claiming
completion. Never advance a footer merely because an earlier message predicted
success.

Use these mappings:

- No stage has started: `not started`.
- Work has started and no gate is waiting: `in progress`.
- Required input, approval, or `needs-human-judgment`: `awaiting user`.
- A prerequisite failed, evidence is stale, or state is blocked/superseded:
  `blocked`.
- The declared command result is verified, delivered/archived, or a one-shot
  action succeeded: `completed`.

## Approval and input prompts

Before the footer, state all four of the following:

- `Why this is needed:` why execution cannot safely continue;
- `Controls:` the decision, artifact, or gate affected;
- `Reply with exactly:` the accepted reply, values, or choices;
- `Tradeoff or safety consequence:` the material effect of each choice.

The final `Next expected update` says what the agent will do after that exact
reply. Do not phrase an approval request as though approval already exists.

## Blockers and completion

A blocked response names the failed prerequisite and evidence, gives the minimum
unblocking action, and states that later gates have not been evaluated. It must
not imply a content failure when the actual problem is missing or stale proof.

A completion response lists verified outputs and names a valid next command. If
there is no next command, say `Workflow complete`. Do not claim completion from
an intended output, an AI-only pass that still needs human approval, or a stale
artifact.

## Prompt-authoring requirements

Every shipped command wrapper declares exactly one ordered workflow, durable
state source, stopping conditions, and valid-next-command list under
`## Workflow guidance`. Every routed command reference declares its detailed
step/state mapping and must not contradict the wrapper. The command's own
declared step names appear in the footer; internal implementation phases do not.

## Examples

### Start

```markdown
The project context is valid. No transcription work has started yet.

**Workflow:** `/avo.transcribe`
**Current step:** Validate inputs — not started
**Next step:** Transcribe sources
**Next expected update:** I’ll report the transcript paths and verification result after transcription starts.
```

### Progress

```markdown
The sources are transcribed; transcript packing is still running.

**Workflow:** `/avo.transcribe`
**Current step:** Pack transcripts — in progress
**Next step:** Verify transcript artifacts
**Next expected update:** I’ll report the packed transcript and any timing errors when verification finishes.
```

### Approval

```markdown
The exact proof and transcript analysis passed, so the picture-lock decision is ready.

Why this is needed: promotion changes the approved candidate used by later stages.
Controls: the picture-lock approval record and downstream motion/audio work.
Reply with exactly: `approve picture lock` or `reject: <reason>`.
Tradeoff or safety consequence: approval locks this candidate; rejection keeps downstream stages closed.

**Workflow:** `/avo.trim`
**Current step:** Picture-lock gate — awaiting user
**Next step:** Record approval or revise the cut
**Next expected update:** After your exact reply, I’ll record the decision and either promote the cut or return to revision.
```

### Blocked

```markdown
Delivery cannot start because the candidate evidence is stale.

Failed prerequisite: current pre-master review evidence.
Evidence: the candidate hash differs from the hash stored in `review.json`.
Minimum unblocking action: rerun `/avo.watch` on the exact candidate.
Later gates have not been evaluated.

**Workflow:** `/avo.deliver`
**Current step:** Validate delivery prerequisites — blocked
**Next step:** Refresh exact-candidate review evidence
**Next expected update:** Run `/avo.watch`; I’ll re-check the candidate hash before delivery resumes.
```

### Completion

```markdown
The final master passed the declared delivery gates.

Verified outputs: master, final-file transcript, delivery manifest, `EDITLOG.md`, and `SOURCE-LOG.md`.
Valid next command: `/avo.learndown`.

**Workflow:** `/avo.deliver`
**Current step:** Finalize delivery — completed
**Next step:** Workflow complete
**Next expected update:** Run `/avo.learndown` when you want the provider-scoped learning wrap; this delivery workflow is complete.
```
