# /avo.audio-qc reference

Delivery loudness and true-peak QC on the **approved master export**. Distinct from `/avo.sound` (mix, NR, restoration, hierarchy).

## Preconditions

- [ ] `provider` + `rawDir` declared
- [ ] Approved **master export** exists under `<rawDir>/edit/masters/` or documented final path
- [ ] **Stop** if only rough cut or unapproved preview — point user to prior pipeline stages

## Parse args

| Arg | Required | Notes |
| --- | -------- | ----- |
| `Provider` | yes | Channel / brand |
| `rawDir` | yes | Workflow root |
| `Footage:` | optional | Master file path; infer latest approved master if omitted |
| Upload candidate | optional | Encoded upload file for post-encode true-peak re-check |

## Load skill

- **`loudness-and-audio-delivery-qc`** — measurement workflow, spot checks, post-encode QC

## Measure

1. Integrated loudness (document standard, e.g. ITU-R BS.1770-style) and settings used.
2. True peak (dBTP) on approved master.
3. **Channel target** from provider notes, `avo.project.json`, or documented internal target — **not** a universal official YouTube number.
4. Optional: loudness range when useful.

## Spot checks

- Sync (dialogue / critical source audio)
- Clipping, distortion, unexpected mutes
- Head/tail pops
- Channel mapping vs stereo/surround intent
- Optional: headphones / laptop speaker intelligibility note

## Post-encode

When user supplies upload candidate (re-encoded export):

- Re-measure true peak on encoded file
- Note delta vs master measurement in audit artifact

## Output

1. **Audio QC** from template:
   - Template: [`docs/templates/review/audio-qc.md`](../../../docs/templates/review/audio-qc.md)
   - Write to: `<rawDir>/edit/review/audio-qc.md`
2. **Result:** PASS/FAIL with release-blocking flags for sync, clipping, pops, mapping defects.

## Workflow

1. Locate approved master; `ffprobe` sample rate and channels.
2. Run loudness/true-peak measurement; document tool and settings.
3. Compare against documented channel target.
4. Run spot-check table; fail closed on release-blocking defects.
5. Re-check encoded candidate if supplied.
6. Hand off to `/avo.deliver` — deliver audio row may link this artifact.

## Handoff

- [`deliver.md`](deliver.md) — full master QC + delivery manifest
- Mix stage boundary: [`sound.md`](sound.md)

## Related

- Editorial skill: `.claude/skills/loudness-and-audio-delivery-qc/SKILL.md`
