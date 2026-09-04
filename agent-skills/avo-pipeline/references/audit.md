# /avo.audit reference

## Step/state mapping

**Durable state:** current review.json and candidate-bound evidence

**Workflow steps:** Validate audit prerequisites → Run audit → Verify and report the audit result

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing required input, a failed or stale gate, a required human decision, or verified audit completion

**Valid next commands:** /avo.watch or /avo.deliver

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
