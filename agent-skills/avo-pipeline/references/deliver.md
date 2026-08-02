# /avo.deliver reference

Full-program master QC and delivery manifest. **Not** `/avo.audit` — audit is scoped to a `from`/`to` window.

## Scope

- Entire approved master export under `<rawDir>/edit/masters/` or documented final path
- If user passes `from`/`to`: **warn** — redirect to [`audit.md`](audit.md) for window QC; deliver assumes full program

## Preconditions

- [ ] `provider` + `rawDir` declared
- [ ] Master export exists (or explicit path via `Footage:`)
- [ ] `EDITLOG.md` / review gates satisfied for picture and audio

## Load skill

- **`final-qc-delivery`** — editorial master QC checklist and delivery manifest behavior

## QC traceability matrix (AGENTS.md Master QC)

| Category | Checks |
| -------- | ------ |
| **Editorial** | Title/thumbnail promise; meaning preservation; facts; conclusion |
| **Audio** | Intelligibility; sync; no clipping/pops; loudness note (method documented); 48 kHz for YouTube master |
| **Visual** | Safe margins; labels; readability; no unintended letterbox; evidence integrity |
| **Captions** | Match final master; names/terms; speaker IDs when needed; non-speech audio where meaningful |
| **Rights / policy** | `SOURCE-LOG.md` complete; sponsorship/affiliate/AI disclosure; privacy/safety review |
| **Technical** | Resolution, aspect, fps, progressive, square pixels; codec/container; clean start/end |

**Fail closed:** if any release-blocking category fails, status is **FAIL** — do not call export upload-ready.

## Final-file transcript (required)

Generate transcript **from the exported master file**, not from rough cut or EDL alone.

- Path: `<rawDir>/edit/transcripts/<master-basename>.txt` (and sidecar formats per project)
- Optional helper: `python -m avo.final_transcript_artifacts` when master path is known

## Output

1. **Delivery manifest** from template:
   - Template: [`docs/templates/delivery/delivery-manifest.md`](../../../docs/templates/delivery/delivery-manifest.md)
   - Write to: `<rawDir>/edit/delivery/delivery-manifest.md`
2. **Pass/fail summary** in agent response with explicit blockers
3. Update `EDITLOG.md` with deliver version, reviewer, status

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

- Window QC: [`audit.md`](audit.md)
- Captions stage: [`captions.md`](captions.md)
- Shorts orchestrator: [`shorts.md`](shorts.md)
- Delivery specs: [`docs/delivery-specifications.md`](../../../docs/delivery-specifications.md)
