# /avo.reframe reference

Extract a vertical (9:16) segment from an approved **long-form master** for Shorts repurposing.

## Preconditions

- [ ] `provider` + `rawDir` declared
- [ ] Human-approved long-form master in `<rawDir>/edit/masters/` or documented review export
- [ ] `from` / `to` window or transcript phrase anchors supplied

**Block** if master is not approved.

## Inputs

| Arg | Required | Notes |
| --- | -------- | ----- |
| `from` / `to` | yes | Segment bounds (also accept `--from` / `--to`) |
| `crop:` or `cropStrategy` | optional | `center` (default), `face-safe`, `custom` |
| `Footage:` | optional | Master path; infer latest approved master if omitted |
| `--preview` | optional | Preview resolution before promotion |

Record in `avo.project.json` when present:

```json
"reframe": {
  "sourceMaster": "edit/masters/...",
  "from": "4:10",
  "to": "4:55",
  "cropStrategy": "face-safe"
}
```

## Execution v1 (agent + ffmpeg)

No mandatory engine module in v1. Optional v1.1: `src/avo/reframe.py` / `python -m avo.reframe`.

1. **Extract segment** from master with ffmpeg (`-ss`, `-to`, stream copy or re-encode per project).
2. **Crop / scale** to 9:16:
   - `center`: center crop to target aspect
   - `face-safe`: bias crop to keep faces and lower-third safe zones when detectable
   - `custom`: user-supplied crop box documented in project notes
3. **Verify** duration, aspect, and intelligibility with `ffprobe` + spot watch.
4. **Name** immutable version: `YYYYMMDD-<slug>-reframe-v001` (increment on re-export).

## Output

- Path: `<rawDir>/edit/intermediates/` or `<rawDir>/edit/preview/`
- Do not overwrite approved long-form master

## Handoff

- Set reframed MP4 as `Footage` for [`shorts.md`](shorts.md) or [`captions.md`](captions.md)
- Continue with `/avo.captions` → `/avo.deliver` when part of Shorts pipeline

## Meaning preservation

- Do not reorder statements across the extract window
- Label if crop removes evidence context (product detail, on-screen proof)
- Do not imply reactions or conclusions not present in source segment

## Related

- Shorts orchestrator: [`shorts.md`](shorts.md)
- Diagnosis: [`guidelines-shorts.md`](guidelines-shorts.md)
- Dealer walkthrough use case: README § Use cases
