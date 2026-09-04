# /avo.podcast-clip Command

**Timeline integration:** Profile

## Workflow guidance

**Workflow steps:** Validate podcast clip prerequisites → Run podcast clip → Verify and report the podcast clip result
**Step state source:** the child pipeline-run.json and its parent timeline lineage
**Stopping conditions:** Missing required input, a failed or stale gate, a required human decision, or verified podcast clip completion
**Valid next commands:** /avo.watch

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

Orchestrated podcast / interview clip extraction with rights, audio QC, and deliver.

**Skill:** [`agent-skills/avo-pipeline/references/podcast-clip.md`](../../agent-skills/avo-pipeline/references/podcast-clip.md)

---

## Usage

```
/avo.podcast-clip
Provider: my-channel
rawDir: /path/to/footage
from: 12:30
to: 18:45
identity: anchor
```

Optional: `--max-duration N` · `--vertical` · `--skip-motion` · `--preview`

---

## Role

Six-phase orchestrator mirroring `/avo.shorts`: diagnosis → trim → watch → optional captions → **rights → audio-qc → deliver** (`podcast-clip` profile).

---

## Instructions

1. Parse `Provider`, `rawDir`, segment bounds (required).
2. Load [`podcast-clip.md`](../../agent-skills/avo-pipeline/references/podcast-clip.md).
3. `--vertical` delegates to [`reframe.md`](../../agent-skills/avo-pipeline/references/reframe.md) when extracting from long-form master.
4. Do not skip rights or audio-qc before deliver.

---

## Example

```text
/avo.podcast-clip
Provider: my-channel
The footage is at C:/Videos/podcast-ep-42
from: 45:00
to: 52:30
identity: documentary
```

## Shared timeline gateway

Runs the base pipeline with format-specific diagnosis and policy. It creates its own timeline context for derivatives and cannot bypass lineage, invalidation, Watch, transcript, or approval gates.
