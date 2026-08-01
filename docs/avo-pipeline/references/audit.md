# /avo.audit reference

## Checklists

### Transcription (`--only-transcription`)

- [ ] Word boundaries respected in EDL
- [ ] Names/terms match user glossary
- [ ] SRT offsets match output timeline formula
- [ ] No cached transcript stale vs source

### Video (`--only-video`)

- [ ] No visible pop/flash at cuts in window
- [ ] Captions not occluded by overlays
- [ ] Grade consistent across segments
- [ ] Duration matches EDL expectation (`ffprobe`)

## Output format

```markdown
## Audit: [window or file]
**Scope:** transcription | video | both
**Result:** PASS | FAIL

| Time | Issue | Suggested fix |
| ---- | ----- | ------------- |
| 9:32 | Audio pop | Extend fade 10ms |
```
