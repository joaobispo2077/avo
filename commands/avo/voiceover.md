# /avo.voiceover Command

**Timeline integration:** Profile

## Workflow guidance

**Workflow steps:** Validate voiceover prerequisites → Run voiceover → Verify and report the voiceover result
**Step state source:** the child pipeline-run.json and its parent timeline lineage
**Stopping conditions:** Missing required input, a failed or stale gate, a required human decision, or verified voiceover completion
**Valid next commands:** /avo.watch

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

Lite merge path: concat clips + external voiceover + EQ/loudness. No motion pipeline.

**Skill:** [`agent-skills/avo-pipeline/references/voiceover.md`](../../agent-skills/avo-pipeline/references/voiceover.md)

---

## Usage

```
/avo.voiceover
Provider: my-channel
rawDir: /path/to/footage
Voiceover: /path/to/vo.wav
Clips: clip_a.mp4, clip_b.mp4
```

Optional: `EDL: edit/edl.json` · `--draft` (720p preview)

---

## Role

Build a minimal voiceover EDL, validate, render ~720p draft for approval, then hand off to `/avo.deliver`. Distinct from `/avo.talking-head` (graphics) and `/avo.captions` (burn-in workflow). TTS/script-only is BL-003 / v2.

---

## Instructions

1. Parse `Provider`, `rawDir`, `Voiceover` (required), and clip list or existing EDL.
2. Run `/avo.sync` when multiple camera/recorder sources need alignment.
3. Write or update `edit/edl.json` with `audio.program_mode: external_voiceover`.
4. Preflight: `python -m avo.voiceover edit/edl.json --preflight-only`.
5. Draft render: `python -m avo.render edit/edl.json -o edit/preview/voiceover-draft.mp4 --draft`.
6. Fill [`docs/templates/review/voiceover-gate.md`](../../docs/templates/review/voiceover-gate.md) → `edit/review/voiceover-gate.md`; wait for explicit approval.
7. After approval, promote to master and run `/avo.deliver`.

---

## Example

```text
/avo.voiceover
Provider: bishop
rawDir: /videos/explainer-01
Voiceover: /videos/explainer-01/vo-final.wav
Clips: /videos/explainer-01/raw/a-roll.mp4
```

## Shared timeline gateway

Runs the base pipeline with format-specific diagnosis and policy. It creates its own timeline context for derivatives and cannot bypass lineage, invalidation, Watch, transcript, or approval gates.
