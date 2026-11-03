# /avo.pipeline Command

**Timeline integration:** Owns

## Workflow guidance

**Workflow steps:** Validate pipeline prerequisites → Run pipeline → Verify and report the pipeline result
**Step state source:** pipeline-run.json main/side state
**Stopping conditions:** Missing required input, a failed or stale gate, a required human decision, or verified pipeline completion
**Valid next commands:** /avo.transcribe

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

Run the full AVO pipeline from declared assets through deliver.

## Resolve motion before engine-specific loading

Parse [shared arguments](../../agent-skills/avo-pipeline/references/arguments.md),
then inspect native `animation engine-show` for the declared project/provider and
optional `--motion-engine hyperframes|remotion|code-drawn` or `Motion engine: <id>`.
Resolve before engine-specific skills, installs or motion authoring, including
motion performed later after a pipeline pause.

Direct "no frameworks" or unqualified "avoid HyperFrames" selects invocation
`code-drawn`; it does not mean `--skip-motion` or save a default. A compatible named
Remotion choice stays explicit and reports its actual unsupported readiness.
Question/quoted-reference/negated-avoidance text is not an execution instruction;
ask once when explicit choices conflict.

For code-drawn motion load the [portable advanced entry](../../agent-skills/avo-pipeline/references/code-drawn.md)
and [selection policy](../../agent-skills/avo-pipeline/references/code-drawn/selection.md).
Do not load HyperFrames-only skills, kits or installation instructions for that
branch. The canonical pipeline and review gates still apply. An unsupported
treatment blocks with its capability explanation; there is no engine substitution.

Pass an explicit choice through native `pipeline run --motion-engine <id>` and
`animation author --motion-engine <id>` when appropriate. Its typed execution choice
survives pauses/resume without writing preferences. A genuine new authoring request
uses `pipeline run --new-request`; existing animation remains pinned until
deliberately revised through the shared services. Inspect future selection,
active `runSelection` and `recordedAnimation` separately. Use `avo cli` installed or
`python -m avo.cli` in a checkout for these core command suffixes.

**Skill:** [`agent-skills/avo-pipeline/references/pipeline.md`](../../agent-skills/avo-pipeline/references/pipeline.md)

**See also:** [`docs/avo-workflow.md`](../../docs/avo-workflow.md) · [pipeline gateway](../../agent-skills/avo-pipeline/SKILL.md)

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

Optional: `--skip-motion`, `--motion-engine hyperframes|remotion|code-drawn`, `--preview`, `--lang pt`

---

## Role

Orchestrate stages 0–7: plan (optional Spec Kit) → transcribe → edit → watch-skill LOOP → **human approval** → motion (unless skipped) → render → deliver → cleanup.

---

## Instructions

1. **Parse inputs and motion intent** per [shared arguments](../../agent-skills/avo-pipeline/references/arguments.md). Inspect the effective engine before loading engine-only workflows.
2. **Resolve provider** manifest and exact project context, then inspect that engine context without saving a default.
3. **Write or update** `<rawDir>/avo.project.json` with declared asset paths only.
4. **Start session (REQUIRED):** use the resolved runtime's `session start --raw-dir <rawDir> --provider <provider> [--title TEXT] [--cost-context <JSON>]`, installed as `avo session start` or checkout `python -m avo.session start`. Supply only explicit metadata context when available; omission records an unknown expected host. This writes `.avo/sessions/<id>/pre.json` baseline inventory for wrap diff and stats.
5. **Inventory** sources (`ffprobe`), transcribe and pack transcripts.
6. **Converse** → propose strategy → **wait for required confirmation**.
7. **Execute** edit proof using its declared profile → current QC/Watch/transcript analysis → write `edit/review/edit-proof/approval-gate.md` → **wait for approval**.
8. Unless `--skip-motion`, author with the selected engine, then generate the canonical motion proof → current review loop → approval gate → promote to the declared source-resolution contract. A standalone code-drawn asset/receipt is not this proof or its approval.
9. **Deliver** master + final transcript; run `/avo.learndown` then `/avo.cleanup` per preserved-set rules (section 7).

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

## Canonical proof planning

After the content maps are current, compile one immutable ProofPlan from the
exact CMap, BMap, Tracks, Animation, Sync Map, source fingerprints, render
profile, and complete iteration RegressionContract. The plan is the sole
orchestration authority for picture, audio, timed events, implementation
references, validation windows, and output identity. Render adapters consume
declared plan timing and parameters; they do not reconstruct editorial intent.

Resolve each requested operation in this order: an AVO built-in, a compatible
provider component, then a registered project-local implementation. When no
supported capability exists, report a structured capability gap before render.
Project-specific Python, shell, PowerShell, JavaScript, or HyperFrames code is
allowed only for that declared unsupported custom delta. Scaffold and register
it inside the external footage project, fingerprint it, and keep its timing and
inputs owned by the same ProofPlan. Never add one-video code to this repository.

Every proof is rebuilt from canonical sources and current deterministic
intermediates. Earlier proofs remain comparison evidence only and are never
picture or audio inputs.

Before a full proof render, run deterministic ProofPlan preflight and stop on
any stale revision, dependency fingerprint mismatch, missing source, output
alias, forbidden recursive media ancestry, unresolved capability, or unavailable
tool. Then render the declared microproof windows plus one representative window
for every changed operation kind and every historical risk window. Microproofs
use the exact same video graph, continuous audio graph, events, implementations,
and parameters as the full proof. Missing, stale, ambiguous, or failed required
microproof evidence blocks the full render. `/avo.pipeline` status must report
the plan hash, preflight state, microproof gate hash, blockers, and the minimum
remediation without claiming that a complete render started.

## Optional artistic start

Accept `--direction none|builtin:<id>@<version>|provider:<id>@r0001|references`, `--brief-context <json>` and repeatable `--direction-reference <descriptor-json>`. Delegate to native pipeline run/briefstart. No selector on an unbound project means raw startup; omission on a bound project retains its exact selected brief. A requested change stays proposed until an exact project decision; never auto-accept or silently choose latest. Present up to three material context questions and two or three concrete options (or a justified singleton), with the complete short view at most 600 visible words.

Before structure/CMap/BMap/motion/sound authoring, read `pipeline status` and `briefing.stageContexts` for the corresponding stage. Honor current instructions, scoped exclusions and protected content. Context is offered, never proof of implementation or media approval. Frozen authorial sources stay in `edit/briefstart` and never authorize historical media reuse.

## Cost recording and completion response

Use the existing runtime to inspect recorded costs (`python -m avo.cli costs --project <project>` in a checkout; `avo costs` installed). Read [cost guidance](../../agent-skills/avo-pipeline/references/costs.md) for explicit context, scoped source attachment and agent/model transitions. Pass available metadata through `--cost-context <JSON>` on pipeline run/resume; reuse an operation ID only for an unchanged retry. No context means unknown expected-host coverage, not a previous agent or inferred human/CI mode.

Context registration measures no conversation and reads no source. Automatic collection requires its exact accepted fact, authorized binding and qualified exact-version profile. Refresh those bound sources with `costs collect` before learndown and after verified cleanup, before final wrap. Missing/denied sources produce scoped diagnostics and editing continues. Skills without an existing runtime cannot claim collection; no hooks, OTel, SDKs or account polling are activated to fill the gap. EOF is not terminal/flush proof.

Learndown MUST automatically display the persisted draft cost/token summary, valuation basis, coverage, cutoff and pending turn before the existing step-status footer. Cleanup MUST automatically display the final persisted summary after verified cleanup and final wrap/export. Only successful production closure can say the video is finished. Accounting/export failure after deletion requires accounting-only retry, never repeating cleanup deletion. Do not generate recursive responses to meter the still-open closing turn.
