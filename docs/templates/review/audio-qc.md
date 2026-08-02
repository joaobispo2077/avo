# Audio delivery QC — {{master-basename}}

**Status:** {{PASS|FAIL}} · **Updated:** {{iso-date}}  
**Provider:** {{provider}} · **Project:** {{rawDir}}  
**Master file:** {{path-under-edit/masters/}}

## Measurement

| Field | Value |
| ----- | ----- |
| Integrated loudness | {{e.g. -14.2 LUFS}} |
| True peak (dBTP) | {{e.g. -1.0 dBTP}} |
| Loudness range (if measured) | {{LU or N/A}} |
| Sample rate / channels | {{e.g. 48 kHz stereo}} |

**Measurement standard / settings:** {{e.g. ITU-R BS.1770-style integrated loudness; tool name and settings}}

**Channel target (documented):** {{from provider notes, project manifest, or internal channel doc — not a universal YouTube requirement}}

**Pass against target:** yes / no — {{brief rationale}}

## Spot checks

| Check | Result | Notes |
| ----- | ------ | ----- |
| Sync (dialogue / critical source) | PASS / FAIL | |
| Clipping / distortion | PASS / FAIL | |
| Pops / mutes at head/tail | PASS / FAIL | |
| Channel mapping (stereo intent) | PASS / FAIL | |
| Intelligibility (headphones / laptop spot) | PASS / FAIL / N/A | |

## Post-encode verification

**Upload candidate file:** {{path or "not supplied"}}

| Field | Master | Upload candidate | Delta |
| ----- | ------ | ---------------- | ----- |
| True peak (dBTP) | {{}} | {{}} | {{}} |

## Release-blocking issues

1. {{issue or "none"}}

## Handoff

- [ ] Link this artifact in `/avo.deliver` audio row when present
- [ ] Do not claim upload-ready until deliver QC passes

---

_Agent: write to `<rawDir>/edit/review/audio-qc.md`. Stop if only rough cut exists — require approved master export._
