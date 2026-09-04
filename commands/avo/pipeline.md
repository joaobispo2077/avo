# /avo.pipeline Command

**Timeline integration:** Owns

## Workflow guidance

**Workflow steps:** Validate pipeline prerequisites → Run pipeline → Verify and report the pipeline result
**Step state source:** pipeline-run.json main/side state
**Stopping conditions:** Missing required input, a failed or stale gate, a required human decision, or verified pipeline completion
**Valid next commands:** /avo.transcribe

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

Run the full AVO pipeline from declared assets through deliver.

**Skill:** [`agent-skills/avo-pipeline/references/pipeline.md`](../../agent-skills/avo-pipeline/references/pipeline.md)

**See also:** [`docs/avo-workflow.md`](../../docs/avo-workflow.md) · [`SKILL.md`](../../SKILL.md)

---

## Usage

```
/avo.pipeline
Provider: my-channel
rawDir: /path/to/footage
Footage: /path/to/main.mp4
SFX: /path/to/sfx/
B-roll: /path/to/broll/
Music: /path/to/music/
```

Optional: `--skip-motion`, `--preview`, `--lang pt`

---

## Role

Orchestrate stages 0–7: plan (optional Spec Kit) → transcribe → edit → watch-skill LOOP → **human approval** → motion (unless skipped) → render → deliver → cleanup.

---

## Instructions

1. **Parse inputs** per [`arguments.md`](../../agent-skills/avo-pipeline/references/arguments.md).
2. **Resolve provider** manifest: `providers/<provider>/avo.provider.json`.
3. **Write or update** `<rawDir>/avo.project.json` with asset paths.
4. **Start session (REQUIRED):** run `python -m avo.session start --raw-dir <rawDir> --provider <provider> [--title TEXT]` — writes `.avo/sessions/<id>/pre.json` baseline inventory for wrap diff and stats.
5. **Inventory** sources (`ffprobe`), transcribe, pack transcripts.
6. **Converse** → propose strategy → **wait for confirmation**.
7. **Execute** edit proof (~360p) → watch-skill LOOP → write `edit/review/edit-proof/approval-gate.md` → **wait for approval**.
8. Unless `--skip-motion`: motion proof (~720p) → LOOP → approval gate → promote to source resolution.
9. **Deliver** master + final transcript; run `/avo.learndown` then `/avo.cleanup` per preserved-set rules (§7).

Report telemetry at each phase boundary (disk, progress, ETA estimate). Pass `session_id` when telemetry helper supports it.

---

## Example

```text
/avo.pipeline
Provider: auto-lot
rawDir: H:/footage/dealer-walk
Footage: H:/footage/dealer-walk/raw/walkthrough.mp4
Music: H:/assets/music/soft-bed.wav
```

## Canonical timeline lifecycle

This command owns the shared lifecycle: intake → sources-ready → sync-ready →
cmap-draft → cut-ai-review → cmap-approved → bmap-draft →
assembly-ai-review → picture-locked → finishing → pre-master-ai-review →
master-approved → delivered → archived. Independently invoked stage/profile
commands call the same transition guards, artifact store, hash invalidation, and
review orchestrator.

Before every human question, validate lineage, render the exact candidate,
transcribe that candidate, run deterministic QC, run Watch over the full program
when practical plus every changed/risk window, auto-fix only reversible defects
inside approved intent using a new revision, and rerun affected checks. Missing
Watch/current transcript blocks. Meaning, rights, disclosure, privacy, safety,
policy, factual conflict, and ambiguous rebase require human judgment.

## Shared timeline gateway

Uses shared timeline storage, transition guards, invalidation, and AI review services. It cannot maintain private CMap, BMap, sync, track, animation, or approval truth.
