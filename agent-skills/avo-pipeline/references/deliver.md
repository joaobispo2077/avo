# /avo.deliver reference

## Step/state mapping

**Durable state:** delivery-manifest.json and current review/approval records

**Workflow steps:** Validate deliver prerequisites → Run deliver → Verify and report the deliver result

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing required input, a failed or stale gate, a required human decision, or verified deliver completion

**Valid next commands:** /avo.learndown

Full-program master QC and delivery manifest. **Not** `/avo.audit` — audit is scoped to a `from`/`to` window.

## Scope

- Entire approved master export under `<rawDir>/edit/masters/` or documented final path
- If user passes `from`/`to`: **warn** — redirect to [`audit.md`](audit.md) for window QC; deliver assumes full program

## Preconditions

- [ ] `provider` + `rawDir` declared
- [ ] Master export exists (or explicit path via `Footage:`)
- [ ] Footage-root `EDITLOG.md` / review gates satisfied for picture and audio (digest from JSON; Human notes for rationale)
- [ ] **Rights:** `<rawDir>/edit/review/rights-audit.md` **PASS** (or run [`/avo.rights`](rights.md) first — **warn** if missing; rights category **FAIL** if `SOURCE-LOG.md` incomplete)
- [ ] **Audio delivery QC:** `<rawDir>/edit/review/audio-qc.md` **PASS** recommended (run [`/avo.audio-qc`](audio-qc.md) on master first)
- [ ] Strict v1.1 assembly materialization is current and matches the exact candidate bytes

## Canonical fidelity gate

Create final candidates through `avo tracks render --render-contract <json>`.
Use optional `--fidelity-policy <json>` only for explicit prohibited classes,
role rules, or policy provenance; no platform resolution or bitrate is implied.
Then run `avo review run --checkpoint pre-master --materialization <record>` and
`avo deliver prepare --materialization <record> --master <immutable-path>`.

The graph includes ordered CMap base segments plus only renderer-compiled
overlays/generators. Declared scale-down can pass; undeclared geometry changes,
unapproved reframes, or proof/proxy base ancestry fail with the exact node.
Missing/stale locks or hashes are blocked prerequisites and require
re-materialization. Details: [`../../../docs/delivery-fidelity.md`](../../../docs/delivery-fidelity.md).

## Load skill

- **`final-qc-delivery`** — editorial master QC checklist and delivery manifest behavior

## QC traceability matrix (AGENTS.md Master QC)

| Category | Checks |
| -------- | ------ |
| **Editorial** | Title/thumbnail promise; meaning preservation; facts; conclusion |
| **Audio** | Intelligibility; sync; no clipping/pops; link [`audio-qc.md`](audio-qc.md) artifact when present (integrated loudness, true peak, method); 48 kHz for YouTube master |
| **Visual** | Safe margins; labels; readability; no unintended letterbox; evidence integrity |
| **Captions** | Match final master; names/terms; speaker IDs when needed; non-speech audio where meaningful |
| **Rights / policy** | `SOURCE-LOG.md` complete; link [`rights-audit.md`](rights.md) artifact when present; sponsorship/affiliate/AI disclosure; privacy/safety review |
| **Technical** | Resolution, aspect, fps, progressive, square pixels; codec/container; clean start/end |

**Fail closed:** if any release-blocking category fails, status is **FAIL** — do not call export upload-ready.

## Final-file transcript (required)

Generate transcript **from the exported master file**, not from rough cut or EDL alone.

- Path: `<rawDir>/edit/transcripts/<master-basename>.txt` (and `.json`, `.md`, `.srt`)
- **Immediately after** a 4K/`--youtube-4k` master render completes, run (or rely on
  `avo.render` auto-step):
  ```bash
  python -m avo.final_transcript_artifacts generate <master.mp4> --edit-dir <rawDir>/edit
  ```
  Or: `python -m avo.transcribe <master.mp4> --edit-dir <rawDir>/edit` then
  `python -m avo.final_transcript_artifacts edit/transcripts/<basename>.json`

**Blocking:** Do not call deliver/cleanup complete until final transcript sidecars exist.

## Output

1. **Delivery manifest** from template:
   - Template: [`docs/templates/delivery/delivery-manifest.md`](../../../docs/templates/delivery/delivery-manifest.md)
   - Write to: `<rawDir>/edit/delivery/delivery-manifest.md`
2. **Pass/fail summary** in agent response with explicit blockers
3. Refresh `<rawDir>/EDITLOG.md` via `python -m avo.cli editlog refresh` (or `avo_editlog_refresh`); append deliver version, reviewer, and status under **Human notes**. Do not hand-write the marked digest.

## Shorts profile

When `deliverable.profile: shorts` in manifest or user declares Shorts deliverable:

- Verify 9:16 aspect and duration policy (default max 60s)
- Document override in `EDITLOG.md` if user approved longer Short
- Cross-ref Shorts fields in delivery manifest template

## Workflow

1. Locate approved master; `ffprobe` technical metadata.
2. Run QC matrix category by category; record PASS/FAIL per row.
3. Confirm or schedule final-file transcript artifact.
4. Write delivery manifest from template; fill all rows honestly.
5. If PASS: state upload-ready **pending user sign-off** on manifest.
6. If FAIL: list blockers; do not promote to upload folder.

## Related

- Rights stage: [`rights.md`](rights.md)
- Audio delivery QC: [`audio-qc.md`](audio-qc.md)
- Window QC: [`audit.md`](audit.md)
- Captions stage: [`captions.md`](captions.md)
- Shorts orchestrator: [`shorts.md`](shorts.md)
- Delivery specs: [`docs/delivery-specifications.md`](../../../docs/delivery-specifications.md)
