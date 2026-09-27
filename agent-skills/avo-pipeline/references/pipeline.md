# /avo.pipeline reference

## Step/state mapping

**Durable state:** pipeline-run.json main/side state

**Workflow steps:** Validate pipeline prerequisites → Run pipeline → Verify and report the pipeline result

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing required input, a failed or stale gate, a required human decision, or verified pipeline completion

**Valid next commands:** /avo.transcribe

Load [`arguments.md`](arguments.md) first.

## Stages executed

| # | Stage | Tool | Inputs | Outputs |
| - | ----- | ---- | ------ | ------- |
| 0 | Plan | Spec Kit (optional) | scope | spec/plan |
| 0b | Session start | `session.py start` | rawDir | `pre.json` |
| 1 | Transcribe | faster-whisper | raw file(s) | **initial transcript** |
| 2 | Edit | render helpers | transcript, EDL | cut proofs |
| 3 | Verify | watch-skill | proof render | agent QC + human gate |
| 4 | Motion | HyperFrames | approved cut | motion proof + human gate |
| 5 | Render | `avo.render --youtube-4k` | approved pre-master | **final master** + **final transcript** (auto) |
| 6 | Deliver | QC + manifest | master + final transcript | delivery manifest |
| 7 | Learndown + cleanup | rimraf | project tree | preserved set only |
## Asset manifest

Write to `avo.project.json`:

```json
{
  "provider": "<provider>",
  "rawDir": "<rawDir>",
  "assets": {
    "footage": "<Footage>",
    "sfx": "<SFX>",
    "inserts": "<B-roll>",
    "music": "<Music>",
    "logos": "<Logo>"
  }
}
```

## Flags

- `--skip-motion`: stop after approved edit master
- `--preview`: hold 360p/720p until user promotes

## JSON-first proof path

Before a proof render, record the current iteration and compile its complete
RegressionContract. Then compile an immutable ProofPlan that locks the active
CMap, BMap, Tracks, Animation and Sync Map revisions, source fingerprints,
render profile, output contract, events and review obligations. Preflight must
stop on conflicting historical decisions, stale dependencies, forbidden media
ancestry, or an unresolved capability. A proof, preview, proxy, master, or
delivery file is comparison evidence only and must never become a render input.

Capability resolution is deterministic: built-in AVO behavior first, compatible
provider components second, and a registered project-local custom implementation
last. Custom code is an escape hatch for one explicitly unsupported delta, not
a parallel orchestration pipeline. Create it under the external footage
project, fingerprint its implementation and dependencies, register its typed
inputs and outputs, and leave all timing, media selection, audio routing and
validation in the ProofPlan. Reusable behavior belongs in AVO or the provider
component library, while video-specific scripts never enter the AVO repository.

### Preflight and microproof gate

Before spending on a full render, validate the exact ProofPlan hash and every
active revision/source lock. Fail closed on missing media, an output path that
aliases an input, recursive proof/preview/proxy/master/delivery ancestry,
unresolved capability references, or unavailable FFmpeg/HyperFrames execution.
Select microproof windows deterministically from declared validation windows,
historical regression risks, and one representative window per changed
operation kind. Render those windows through the same immutable video graph,
continuous audio graph, TimedEvents, implementation references, and adapter
parameters as the full proof. Do not create a special lightweight edit path.

A full build requires a gate whose ProofPlan and preflight hashes are current,
whose required-window set is complete, and whose results all pass. `failed`,
`ambiguous`, `needs-human-judgment`, missing, or stale evidence blocks the full
render. Status output names the exact blocker and minimum remediation while
keeping the expensive render unstarted.
