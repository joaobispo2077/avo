# /avo.end-screen reference

## Step/state mapping

**Durable state:** pipeline-run.json plus the current canonical timeline revision

**Workflow steps:** Validate end screen prerequisites → Run end screen → Verify and report the end screen result

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing required input, a failed or stale gate, a required human decision, or verified end screen completion

**Valid next commands:** /avo.deliver

Upload prep: **YouTube end-screen** safe zone and asset checklist.

## Preconditions

- [ ] Approved master under `edit/masters/` or documented final path
- [ ] `ffprobe` duration known

## Workflow

1. Review final **20 seconds** of master for UI overlap risk (subscribe button, suggested video zones).
2. Confirm CTA/subscribe graphics do not cover faces, captions, or critical evidence.
3. Fill template [`docs/templates/review/end-screen-checklist.md`](../../../docs/templates/review/end-screen-checklist.md).
4. Write `<rawDir>/edit/review/end-screen-checklist.md` with PASS/FAIL.

## Related

- Chapters: [`chapters.md`](chapters.md)
- Deliver: [`deliver.md`](deliver.md)
- YouTube end screens: [official docs](https://support.google.com/youtube/answer/6388789)
