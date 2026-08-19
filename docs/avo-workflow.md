# AVO Workflow (agent-facing deep dive)

> Canonical runtime amendment: Python services under `avo.timeline` own the
> lifecycle and all mutations. `edit/timeline/{sync-map,cmap,bmap,tracks,animation}.json`
> are canonical indexes over immutable revisions/events. `edit/edl.json` is a
> generated renderer projection. CMap is always raw-based; BMap is always based
> on the latest effective approved CMap cut output. Exact-candidate Watch,
> transcription, and checkpoint QC run before any human gate. Legacy projects
> use `python -m avo.cli migrate-timeline plan|apply|validate|activate|rollback`;
> cleanup requires a verified reconstruction bundle.


This is the precise, unambiguous specification of the AVO pipeline for the coding
agent driving it. `AGENTS.md` is canonical; this document expands the workflow
mechanics and must not contradict it. The user-facing summary lives in
[`../README.md`](../README.md).

AVO is a **thin orchestration layer**. The agent routes each stage to the tool
that owns it (see [`../README.md`](../README.md) routing table). Every stage
below names its **owning tool**, its **inputs**, and its **outputs**.

---

## 1. Per-video project model

- **One video = one project.** A project is the raw-footage folder plus its
  `edit/` subtree. Work happens *inside* that folder, never inside the AVO repo.
- **Provider tag.** Every project is tagged to exactly one **provider** (a
  YouTube channel, TikTok account, Instagram profile, …). The provider supplies
  brand/design/routing defaults; self-learning is scoped to it (§8).
- **Declare inputs first (blocking precondition).** Before any stage runs, the
  project MUST declare:
  - `provider` — the provider name (resolves to `providers/<name>/avo.provider.json`).
  - `rawDir` — the raw-files folder. **This folder is the workflow root**; when
    planning with SpecKit, SpecKit MUST be told this is where work happens.
  - `assets` — locations of `sfx`, `music`, `inserts`, `graphics`, `logos` (any
    that apply). Paths only; media stays external and gitignored.
- **Project layout (external to the repo):**

  ```
  <video_project>/
    raw/                      # untouched source (PRESERVED)
    edit/
      timeline/               # canonical indexes + immutable revisions/events
      transcripts/            # initial + final transcripts (PRESERVED)
      preview/                # proof MP4s for human watch (360p / 720p / pre-master)
      review/                 # human approval packages (see §4b)
        edit-proof/
        motion-proof/
        pre-master/
      masters/                # final master (PRESERVED)
      ...intermediates...     # deleted by post-render cleanup (§7)
  ```

  Canonical layout: [`templates/project-layout.md`](templates/project-layout.md).

---

## 2. Stage map (owning tool · inputs → outputs)

| # | Stage | Owning tool (Local) | Inputs | Outputs |
| - | ----- | ------------------- | ------ | ------- |
| 0 | Plan & spec | GitHub Spec Kit (`/speckit.*`) | `/speckit.specify`, `rawDir`, provider manifest | spec/plan/tasks for the video |
| 1 | Transcribe | video-use + faster-whisper (lang @ setup) | raw file(s), language | **initial transcript** (word-timed) |
| 2 | Edit / cut | AVO timeline + renderer | raw inventory, SyncMap, transcript | raw CMap, generated EDL, cut proof |
| 3 | Understand / verify (THE LOOP) | watch-skill (MCP/CLI/REST) | proof render | confidence score, defect list, fix directives → **human approval gate** (§4b) |
| 4 | Motion / animation | HyperFrames (default) → Remotion | **user-approved** cut, brand tokens | motion proof render → **human approval gate** (§4b) |
| 5 | Render / encode | local render helpers (Paid: gemini-flow) | user-approved motion + cut | resolution-promoted render; **`--youtube-4k` also runs final PT-BR transcript** |
| 6 | Deliver | video-use | approved 1080p render | **final master** + **final transcript** |
| 7 | Learndown + cleanup | ai-memory (optional) + rimraf | full project tree | preserved set only; learning filed by provider |

Paid alternatives (`ElevenLabs` for transcription, `gemini-flow` for render) are
opt-in swaps for the same stage and produce the same output contract.

---

## 3. Confidence gate & low-res loop

AVO does not render at full quality until it is confident. Confidence is decided
by the watch-skill LOOP (§4), not by wall-clock or iteration count.

- **Low confidence → cheap proofs:**
  - **≈360p** at the **edit stage** (video-use, stage 2).
  - **≈720p** at the **motion stage** (HyperFrames/Remotion, stage 4).
- **High confidence → promote to 1080p** (stage 5).
- **Each iteration** preserves immutable decision/evidence metadata. Bulky
  superseded proof media may be pruned only after its hash/provenance is recorded.
- **Final resolution is inferred from the raw files.** 1080p above is the common
  case; if the source is lower, the target is the source resolution.
  **Above-source output is NOT supported.** See
  [BL-002 in docs/ROADMAP.md](ROADMAP.md#backlog-sponsor-friendly).

```
   edit intent
       │
       ▼
  [360p edit proof] ──► watch-skill LOOP ──► agent transcript analysis
       ▲                                        │
       └──────── fix ◄── not approved ◄────────┤
                                                ▼
                                    ⏸ HUMAN APPROVAL GATE (edit-proof)
                                                │ approved
                                                ▼
  [720p motion proof] ─► watch-skill LOOP ─► agent transcript analysis
       ▲                                        │
       └──────── fix ◄── not approved ◄────────┤
                                                ▼
                                    ⏸ HUMAN APPROVAL GATE (motion-proof)
                                                │ approved
                                                ▼
                                    [promote to 1080p / source res]
                                                ▼
                                    ⏸ HUMAN APPROVAL GATE (pre-master)
```

---

## 4. The watch-skill LOOP (inspect → fix → verify)

Owning tool: [watch-skill](https://github.com/oxbshw/watch-skill) (local-first;
MCP, CLI, or REST). Runs alongside **every** render-producing stage.

1. **Inspect.** watch-skill views the current proof render.
   - Inputs: proof render (path), stage intent, acceptance criteria.
   - Outputs: a confidence score and a concrete defect list (what is wrong and
     where).
2. **Decide confidence (internal).**
   - **High** → agent may stop looping fixes; **does not** auto-promote (§4b).
   - **Low** → emit fix directives and loop.
3. **Fix.** The agent applies the fix directives to the owning tool of that stage
   (video-use for cuts/captions; HyperFrames/Remotion for motion).
4. **Verify.** Re-render the proof and re-inspect. Repeat until confidence is
   high or the agent escalates to the user.
5. **Transcription analysis.** Agent reviews the current transcript against the
   proof (names, terms, caption alignment, cut intent) and records findings in
   the review package (§4b).

**LOOP invariants:**
- The LOOP operates on **proof resolution**, never full resolution, until
  the user approves promotion (§4b).
- Every LOOP pass deletes the superseded proof (no stale files).
- The LOOP is advisory-plus-gating: it *gates internal re-proof* but never
  replaces **human approval** (§4b), never fabricates content, and never
  overrides editorial-intent rules in `AGENTS.md`.

---

## 4b. Human approval gate (blocking)

## Agent pre-human gate (blocking)

Before writing `approval-gate.md` or asking the creator to watch:

1. **Canonical validation** — raw CMap, effective CMap-bound BMap, dependency hashes, and generated projection are current.
2. **Transcript read** — cut edges, privacy spans, names/terms; cite source times.
3. **`/avo.watch`** — proof render with timestamps at range joins, blocked B-windows,
   and every overlay beat.

Fix → re-render → repeat. **Only then** open the human approval gate (§4b).

**Checkpoints:** `edit-proof` · `motion-proof` · `pre-master`

| Checkpoint | User opens first | Review package |
| --- | --- | --- |
| edit-proof | `edit/preview/edit-proof.mp4` (or legacy `preview.mp4`) | `edit/review/edit-proof/approval-gate.md` |
| motion-proof | `edit/preview/motion-proof.mp4` | `edit/review/motion-proof/approval-gate.md` |
| pre-master | `edit/preview/pre-master.mp4` | `edit/review/pre-master/approval-gate.md` |

**Agent MUST:**

1. Write canonical `edit/review/<checkpoint>/<candidate>/review.json` and
   derive `approval-gate.md` using
   [`templates/review/approval-gate-manifest.md`](templates/review/approval-gate-manifest.md).
2. List every path the user should open (preview MP4, EDL, transcript JSON, stills).
3. Summarize the exact immutable revision/diff changes, where/why they occur, stale dependencies, Watch, and transcription analysis in plain language.
4. Ask explicitly: **Approve to promote / advance, or request changes?**
5. **Wait** for user response. Never assume approval because watch-skill confidence
   is high.

**On approval:** set manifest status to `approved` with ISO date; AVO refreshes
`<rawDir>/EDITLOG.md` (digest from JSON). Agents append rationale under **Human
notes** — do not hand-edit the marked digest or treat `edit/project.md` as the
audit. Then and only then promote resolution or advance stage.

**On changes requested:** loop back through fix → proof → §4 (LOOP + analysis) →
new approval gate.

**Config:** `avo.project.json` → `approvalGates.requireHumanSignOff` (default
`true`). See [`../schemas/avo.project.schema.json`](../schemas/avo.project.schema.json).

Spec: [`../specs/active/avo-approval-gates-ux/spec.md`](../specs/active/avo-approval-gates-ux/spec.md).

---

## 5. Telemetry expectations

Every phase boundary MUST report both a human-readable line and a
machine-readable JSON line the agent can consume. Rolling stats are written to
`.avo/state.json` (gitignored). No wall-clock timing in deterministic render
paths.

Each report includes:

- **Disk free** on the volume where editing happens (the `rawDir` volume).
- **Step bytes** — bytes the step just created.
- **Cumulative footprint** — total bytes the project currently occupies.
- **Phase progress** — phase N of total, plus percent.
- **Rough ETA** — estimated from elapsed time and step history, **labelled as a
  rough estimate**, never a promise.

Learndown telemetry (§7) additionally reports:

- **Space used** across all iterations vs **space freed** by cleanup.
- **Preserved-set size** after cleanup.

Example human line (illustrative form):

```
[phase 4/6 · motion proof 720p] disk free 812.4 GB · step +1.9 GB ·
project 6.3 GB · 66% · ~4m left (rough)
```

Example JSON line (illustrative shape — field names match `src/avo/telemetry.py`):

```json
{"phase":"motion-proof","index":4,"total":6,"percent":66.0,"diskFreeBytes":872000000000,
 "createdBytes":1900000000,"cumulativeBytes":6300000000,"etaSeconds":240.0,"ts":"2026-08-01T12:00:00Z"}
```

---

## 6. Hardware capability advisory

Owning helper: `src/avo/hardware.py` (probed on render/watch phases). **Advisory
only — it never blocks a run.**

- Probes: CPU (cores/model), RAM, GPU (name/VRAM via `nvidia-smi` / `wmic` /
  `system_profiler`), free disk. Degrades gracefully to `"unknown"` per field.
- Emits a JSON capability report plus a suggested tier map, e.g.
  `{ "whisper": "large-v3" | "small", "llm": "qwen2.5-7b" }`.
- Catalog ids and alternatives live in [`avo.model-catalog.json`](../config/avo.model-catalog.json);
  resolve active tiers with `python -m avo.models_cli show` or
  [`docs/model-transparency.md`](model-transparency.md).
- **The agent reads the report and tells the user, in prose, what it selected and
  the better/worse alternatives.** Because AVO is agent-driven, the advisory
  becomes a recommendation, not an automatic switch.

**Advisory message form (canonical shape the agent should produce):**

> Detected: `<CPU model, N cores>`, `<RAM> GB` RAM, GPU `<name, VRAM>`, `<free>`
> free on the edit volume. For this hardware I used **`<understand label>`** +
> **`faster-whisper-<y>`**. A higher-quality option is `<larger tier>` (slower /
> more VRAM); a lighter option is `<smaller tier>` (faster / lower quality). This
> is advisory only — say the word to change tiers.

`<understand label>` is the catalog label for the resolved understand option
(default **Qwen 2.5 7B** / `qwen2.5-7b`; a pinned Bonsai label is valid when
`models.understand` points at an optional Bonsai GGUF id). Keep the
`faster-whisper-<y>` / Qwen examples for the default case.

When mentioning Bonsai, lead with capacity: **Bonsai 27B 1-bit ~4–8 GB VRAM
(≈ Qwen3.6-27B ~54 GB FP16)**; **ternary ~7–12 GB VRAM (≈ same Qwen3.6-27B
~54 GB FP16)**. Do not call Bonsai “a 7B” or “a rename of Qwen 2.5 32B”. Load
path (llama-server + `setup-vision --provider custom`) and the full table: see
[`docs/model-transparency.md`](model-transparency.md).

---

## 7. Post-render learndown + cleanup

Runs after the final master is approved. Pipeline kickoff starts a **session**
(`python -m avo.session start`) and writes `.avo/sessions/<id>/pre.json` as
a baseline inventory. After cleanup, a **session record** lands in
`.avo/state.json` and per-video **wrap artifacts** survive on the footage volume.

**Orchestrator scratch roots.** Ephemeral QC, proofs, contact sheets, caption
experiments, and session dumps the orchestrator or its agent workflow creates
must land in a remembered root:

- `.avo/tmp/<kind>/<session-id>/` with kinds `learndown`, `qc`, `shorts-proof`,
  `session` (via `avo.scratch.scratch_path` / `avo.avo_state.tmp_dir`), or
- `<rawDir>/edit/` for footage preview, verify, and review proofs.

Repo-root `.tmp-*` is a defect. Never write QC or proofs into the AVO clone
(repo root, `specs/`, and `src/` included). Footage `edit/` proofs belong on the
footage volume; they are not orchestrator-repo files. A writer that cannot use
those roots must fail closed with remediation pointing at `avo.scratch` /
`avo.avo_state.tmp_dir` — do not silently fall back to `.tmp-*`. Existing
repo-root tmp (`.tmp-*`, `.codex-qc/`, `.codex-tmp/`, `.avo-test-sessions/`,
`NUL`, `err.txt`, `out.txt`, `*.orig`) is listed for delete, never committed,
and removed only after explicit user confirm.

Two steps, in order:

1. **Learndown (draft wrap + optional ai-memory).** Condense iteration learnings
   toward the approved master under the **provider** scope (§8). **Without
   ai-memory, only MCP wiki consolidation is skipped** — inventory, draft wrap,
   provider export, and telemetry still run; cleanup proceeds normally.
   - **Inventory report:** `project_inventory.py report` (uses `pre.json` when
     present for added/removed/modified classification). Default `--json` is
     compact counts + sample; `--scratch-out --session-id` still writes the
     **full** report under `.avo/tmp/learndown/<id>/`. `--full-paths` is
     debug-only. Agents MUST call this CLI (or MCP that wraps it). Ad-hoc
     `.avo/tmp/**/execute_*.py` walk/delete scripts are out of contract.
   - **Draft wrap (REQUIRED):** `<rawDir>/avo.wrap.draft.md` and
     `avo.wrap.draft.json` (`status: "draft"`) — outside `<rawDir>/edit/`.
     Includes narrative summary, **sample** scheduled deletions (`deletedCount`
     is the true total), preserved artifacts, space estimates, ai-memory note.
     **Provider export (REQUIRED):** wrap also writes
     `providers/<slug>/learndowns/<entry-id>/` (`learndown.json`, `learndown.md`,
     wrap copies, and a first-copy `EDITLOG.md` lock when footage-root EDITLOG
     exists) and updates `providers/<slug>/learndowns/index.json`. Use
     `python -m avo.wrap draft … --no-export` only when debugging.
   - **Scratch inventory (optional):** `project_inventory report --scratch-out
     --session-id <id>` stages full JSON under `.avo/tmp/learndown/<id>/` — never
     at repo root.
   - **Learndown telemetry:** `Telemetry.learndown()` — space used vs freed
     preview and preserved-set size (§5).
2. **Cleanup (rimraf + final wrap + stats record).** Delete everything the run
   created in the video project folder **except** the preserved set.
   - **Windows `rawDir`:** `--project` maps WSL paths `/mnt/<letter>/...` to
     `<letter>:\...`. If the mapped path is missing and `avo.project.json`'s
     parent contains `edit/`, that parent is used. Otherwise fail closed.
   - **Verify:** `python -m avo.cli cleanup verify --project <avo.project.json>
     --master-basename <stem>` — compact JSON (`status`, `verifyErrors`); refuse
     if preserved set incomplete.
   - **Dry-run:** `python -m avo.cli cleanup dry-run --project <avo.project.json>
     --master-basename <stem> [--session-id <id> --scratch-out]` — compact JSON
     (`candidateCount`, `candidateSample`, leftover OSError skips). Writes
     nothing. `--full-paths` is debug-only.
   - **Execute:** `python -m avo.cli cleanup execute --project <avo.project.json>
     --master-basename <stem> [--session-id <id>]` — not a dry-run. Prints
     compact JSON **before** session tmp purge. Assert delete list ∩ preserved
     set = ∅, then `rimraf` footage delete candidates under `<rawDir>/edit/`.
     Walk/unlink `OSError` skips that path and increments `leftoverCandidates`.
     On success with `--session-id`, purge **all** session kinds under
     `.avo/tmp/<kind>/<session-id>/` (`learndown`, `qc`, `shorts-proof`,
     `session`). Incomplete preserved set or preserved ∩ delete refuses the run
     and skips purge (`status: blocked`).
   - **Legacy vs canonical:** when all five canonical indexes exist, the
     reconstruction bundle remains required. When they are absent, execute
     copies `edit/edl.json` / `edl-v*.json` / edit logs into
     `edit/review/legacy-reconstruction/` and root `EDITLOG.md` /
     `AUDIO-EDITLOG.md` (dry-run does not write). Do not use migrate-timeline
     for that copy.
   - **Final wrap (REQUIRED):** `<rawDir>/avo.wrap.md` and `avo.wrap.json`
     (`status: "final"`) with actual freed bytes (inherited from the draft when
     post-delete candidates are empty) and **sample-capped** deleted file lists
     plus `deletedCount`. Draft wrap files are **retained** for audit
     comparison. Re-exports the provider learndown entry with `status: "final"`
     and final wrap copies when present. An existing `EDITLOG.md` lock in that
     entry is not overwritten.
   - **Session record (REQUIRED):** `python -m avo.stats record
     --wrap-json <rawDir>/avo.wrap.json` → `.avo/state.json` → `stats.sessions[]`
     + cumulative `stats.totals`.
   - Optional cleanup telemetry via `Telemetry.cleanup()`.

**Preserved-set invariant (release-blocking).** After cleanup, the verified reconstruction graph survives:

- the **raw file**,
- the **initial transcript**,
- the **final transcript**,
- the **final master** output,
- canonical timeline indexes, immutable revisions/events, projection lineage,
- candidate-bound review evidence and exact approvals,
- `edit/timeline/reconstruction-bundle.json`.

> The final transcript MUST be generated from the final exported master itself
> (per `AGENTS.md` → Captions And Accessibility), not from the source footage or
> an intermediate export. Store it under `edit/transcripts/` using the master
> basename.

Cleanup MUST use cross-platform deletes (`rimraf`), never `rm -rf` / `del`, and
MUST refuse to delete anything in the preserved set.

**Aggregate metrics:** `/avo.stats` (or `python -m avo.stats show`) reads
local session history only — no network. Privacy: [`SECURITY.md#privacy--telemetry`](../SECURITY.md#privacy--telemetry).

---

## 8. Provider-scoped learning

- **Scope.** AVO accumulates learning across videos from the **same provider**,
  while each video remains a separate project.
- **In-repo, tracked:** provider identity/design/brand under
  `providers/<name>/` — `avo.provider.json` (manifest), `DESIGN.md`, `logo/`,
  `brand/` (palette, caption/lower-third presets), and **learndown exports** under
  `providers/<name>/learndowns/` (`index.json` + one folder per master).
- **External, gitignored:** all media. The manifest stores **paths only**
  (`media.rawRoot`, asset dirs); no footage enters the repo.
- **Resolution flow.** A project reads its provider manifest to resolve brand +
  external roots + routing overrides + default transcription language, then
  layers the per-video `avo.project.json` (`rawDir`, `assets`, `provider`) on top.
- **Learning target.** The next video for the same provider starts from the
  consolidated learndown, improving cut/caption/motion decisions over time —
  without ever merging two videos into one project.

---

## 9. Stage-by-stage checklist (agent quick reference)

- [ ] Inputs declared: `provider`, `rawDir` (told to SpecKit as the workflow
      root), `assets`.
- [ ] Provider manifest resolved; brand/routing/lang defaults loaded.
- [ ] Initial transcript produced (video-use + faster-whisper) and preserved.
- [ ] Edit proof at ≈360p; watch-skill LOOP; agent transcription analysis;
      **human approval gate** (`edit/preview/`, `edit/review/edit-proof/`).
- [ ] Motion proof at ≈720p; watch-skill LOOP; agent transcription analysis;
      **human approval gate** (`edit/review/motion-proof/`).
- [ ] Promote to 1080p / source resolution (never above source) **after pre-master
      human approval**.
- [ ] Telemetry reported at every phase boundary (disk / step / progress / ETA).
- [ ] Hardware advisory surfaced on render/watch phases (advisory only).
- [ ] Final master approved; final transcript generated from the master.
- [ ] Learndown: draft wrap (`avo.wrap.draft.*`); inventory report; space preview telemetry.
- [ ] Cleanup: verify preserved set → execute rimraf → final wrap → `stats record`.
- [ ] Cleanup keeps only: raw, initial transcript, final transcript, final master.
- [ ] `/avo.stats` shows cumulative totals (local only — [`SECURITY.md#privacy--telemetry`](../SECURITY.md#privacy--telemetry)).

---

## Related docs

- [`../README.md`](../README.md) — user-facing overview and routing table.
- [`../AGENTS.md`](../AGENTS.md) — canonical agent rules (includes the AVO
  operating section).
- [`editing-system.md`](editing-system.md),
  [`audio-post-production-system.md`](audio-post-production-system.md),
  [`animation-system.md`](animation-system.md) — per-domain systems.
- [`delivery-specifications.md`](delivery-specifications.md) and siblings —
  delivery specs.

## Canonical timeline lifecycle

Canonical video state lives in edit/timeline/{cmap,bmap,tracks,animation,sync-map}.json with immutable revisions and stable-ID diffs. edit/edl.json is generated renderer compatibility output. Lifecycle: intake → sources-ready → sync-ready → cmap-draft → cut-ai-review → cmap-approved → bmap-draft → assembly-ai-review → picture-locked → finishing → pre-master-ai-review → master-approved → delivered → archived. All 51 commands declare Owns, Evidence, Consumes, Profile, or Admin and share guards, invalidation, and review. Missing current Watch/transcript blocks. Cleanup preserves compact reconstruction metadata.
