# /avo.watch reference

## Step/state mapping

**Durable state:** current review.json and approval record

**Workflow steps:** Validate watch prerequisites → Run watch → Verify and report the watch result

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing required input, a failed or stale gate, a required human decision, or verified watch completion

**Valid next commands:** the declared human approval gate

Full **THE LOOP** via watch-skill. See [`docs/avo-workflow.md`](../../avo-workflow.md) §4.

**Blocking:** Do not open the human approval gate until watch-skill **and** transcript
analysis both pass. Cut/motion proofs also require [`cuts.md`](cuts.md) pre-review.

## Steps

1. Select proof render (`edit/preview/*.mp4`).
2. Run `python -m avo.edl_timeline verify edit/edl.json` when EDL changed.
3. **Transcript read:** confirm cut edges, privacy spans, names/terms; record source
   times in the review package.
4. watch-skill: inspect → defect list → confidence. Pass `--timestamps` for every
   range join, blocked-range B-window, and overlay `start_in_output`.
5. Agent applies fixes to owning stage tool.
6. Re-render proof; repeat until stable or user intervenes.
7. Write approval package:

```
edit/review/<checkpoint>/
  approval-gate.md
  (links to preview + analysis)
```

6. **Block** until user says approve.

## Agent pre-human gate (required)

Complete **before** step 7 above and before asking the creator to watch:

| Check | Tool |
| --- | --- |
| Source↔B-time consistency | `python -m avo.edl_timeline verify` |
| Cut/privacy correctness | Transcript JSON + [`cuts.md`](cuts.md) |
| Visual QC | watch-skill with boundary/overlay timestamps |

See [`cuts.md`](cuts.md) for the full cut-map / beat-map requirements.

## Checkpoint names

- `edit-proof` — after cut proof
- `motion-proof` — after motion proof
- `pre-master` — before 1080p/source promotion

## Non-overridable AI-first gate

Human review opens only after current candidate Watch evidence, current-candidate
transcript analysis, and all checkpoint-specific deterministic checks. Evidence
is fresh only when candidate and dependency hashes match exactly. Missing Watch
or transcript remains `blocked`; do not hide a waiver in chat.

Safe automatic fixes must be reversible, remain inside approved intent, create
a new immutable revision, invalidate affected evidence, and rerun checks.
Meaning, chronology, rights, disclosure, privacy, safety, policy, factual
conflict, and ambiguous rebase become `needs-human-judgment`. Persist attempts,
blockers, coverage, and recovery commands in `review.json`; generate
`approval-gate.md` only as its human-readable projection.

## Configurable execution policy

Before invoking Watch, resolve the shared policy field-by-field and validate it.
Use `avo review policy --project <avo.project.json>` for read-only inspection.
Forward only declared format, language, acceptance criteria, risk notes,
transcript reference, validated terms/names, and required windows. Never infer a
project topic or language. Only explicit `device=cpu` forces CPU. Preserve raw
attempts and outcome kind; uncertainty/refusal routes to human judgment, while
tool, malformed, or coverage errors block. Full controls and examples:
[`docs/watch-review-policy.md`](../../../docs/watch-review-policy.md).
