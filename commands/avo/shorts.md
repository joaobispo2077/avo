# /avo.shorts Command

**Timeline integration:** Profile

Orchestrated YouTube Shorts workflow (9:16, duration checks, captions, deliver). **Not** the same as `/avo.guidelines --shorts` (diagnosis only).

**Skill:** [`agent-skills/avo-pipeline/references/shorts.md`](../../agent-skills/avo-pipeline/references/shorts.md)

---

## Usage

```
/avo.shorts
Provider: my-channel
rawDir: /path/to/footage
identity: anchor
```

Optional agent hints: `--from-master` · `--max-duration 60` · `--skip-motion` · `--preview`

`--from-master` and `--skip-motion` are agent orchestration hints only. Express extraction intent in
`shorts.request.json`. Executable preview renders use:

```bash
python -m avo.shorts build <plan> --stage proof --preview
```

`--preview` produces 640×360 proofs for cheap review before full-resolution rebuild.
After preview, a full-resolution `build --stage proof` automatically marks every
item dirty via `renderProfile` mismatch and rebuilds at plan output size.

---

## Batch usage

```text
/avo.shorts
Provider: bishop
Master: /path/to/approved-master.mp4
Transcript: /path/to/approved-master.json
Count: 10
Destination: youtube-shorts
Language: pt-BR
Max duration: 60
```

The agent performs transcript-backed idea selection and writes one canonical
`shorts.request.json`. The executable workflow validates and resolves that
request:

```bash
python -m avo.shorts validate /path/to/shorts.request.json
python -m avo.shorts resolve /path/to/shorts.request.json \
  -o /path/to/plans/shorts.plan-v001.json
```

Resolution produces exactly `Count` plan-owned entries or stops with an
actionable insufficiency/meaning-preservation finding. It never renders proofs
and always leaves the new plan at the batch-plan approval gate.

After recording approval on that immutable plan revision:

```bash
python -m avo.shorts build <plan> --stage proof --workers 2
python -m avo.shorts build <plan> --stage proof --preview
python -m avo.shorts qc <plan> --stage proof
python -m avo.shorts status <plan>
python -m avo.shorts promote <plan> --approval-manifest approvals.json
```

Use repeated `--short 04` filters for targeted rebuild/QC. Proof and master
revisions are immutable; unchanged clean items are reused, while failed items
remain retryable without cancelling or overwriting approved siblings.

---

## Role

Phase 0 Shorts diagnosis → transcript-backed batch planning → human plan
approval → parameter-driven proofs → watch-skill LOOP → picture lock → QC →
immutable delivery. HyperFrames is an internal renderer and is not part of the
user-facing command contract.

---

## Instructions

1. Parse `Provider`, source/master, destination, language, count, and duration.
2. Run phase 0 from [`guidelines-shorts.md`](../../agent-skills/avo-pipeline/references/guidelines-shorts.md).
3. For batch mode, derive distinct candidates from the word transcript, persist
   the request, validate it, and resolve one immutable plan revision.
4. Present candidate order, evidence, source ranges, durations, speed/layout,
   caption anchors, and resolved insertion assignments for human approval.
5. Do not build a proof or master until the exact plan revision is approved.
6. If `--from-master`, preserve the approved source reference and express each
   extraction in the batch request instead of creating project-specific code.
   This is an agent workflow hint; the Python CLI does not implement a
   `--from-master` flag.
7. Warn and block promotion when duration exceeds `--max-duration` (default
   60) without an explicit reviewed override.
8. Insertions use only approved source windows and a concrete selected audio
   stream. Finite repetition is materialized before composition; browser loops
   are forbidden.
9. Record Watch review for insertion semantics (for example active gameplay).
   Black/freeze scans are supporting evidence and cannot replace that review.
10. Promotion requires motion-proof, picture-lock, rights, and pre-master
    approvals plus passing QC and fresh JSON/SRT/TXT/MD transcripts generated
    from each exact delivered master.

---

## Example

```text
/avo.shorts
Provider: my-channel
The footage is at C:/Videos/short-001
identity: anchor
```

Existing single-Short usage remains supported. Batch mode is selected by
supplying `Count` plus a master/request; `/avo.guidelines --shorts` remains
diagnosis-only.

## Shared timeline gateway

Runs the base pipeline with format-specific diagnosis and policy. It creates its own timeline context for derivatives and cannot bypass lineage, invalidation, Watch, transcript, or approval gates.
