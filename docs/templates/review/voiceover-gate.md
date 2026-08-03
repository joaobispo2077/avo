# Voiceover preview gate — {{program-title}}

**Status:** {{PENDING|APPROVED|BLOCKED}} · **Updated:** {{iso-date}}  
**Provider:** {{provider}} · **Project:** {{rawDir}}

## Artifacts

| Artifact | Path | Notes |
| -------- | ---- | ----- |
| Draft preview | `edit/preview/voiceover-draft.mp4` | ~720p `--draft` render |
| EDL | `edit/edl.json` | `program_mode: external_voiceover` |
| Voiceover source | {{vo-path}} | External file (not TTS v1) |

## Checks

| Check | Result | Notes |
| ----- | ------ | ----- |
| Cut timing matches VO narration | PASS / FAIL | |
| Speech intelligibility (VO track) | PASS / FAIL | |
| No unintended camera/dialogue bleed | PASS / FAIL | Video-only segments |
| Loudness/EQ acceptable for format | PASS / FAIL | |
| Meaning preserved vs script/story map | PASS / FAIL | |

## Blockers

1. {{or none}}

## Approval

- [ ] User explicitly approved promotion to final master
- [ ] Ready for `/avo.deliver`

---

_Agent: write to `<rawDir>/edit/review/voiceover-gate.md` after draft render and transcription review._
