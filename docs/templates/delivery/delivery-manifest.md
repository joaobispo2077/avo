# Delivery manifest

**Version:** `YYYYMMDD-<slug>-master-v001`  
**Profile:** long-form | shorts | tiktok | podcast-clip | trailer  
**Generated:** YYYY-MM-DD  
**Status:** PASS | FAIL

---

## Files

| Role | Path | Notes |
| ---- | ---- | ----- |
| Master | `<rawDir>/edit/masters/...` | Approved upload candidate |
| Final transcript | `<rawDir>/edit/transcripts/<master-basename>.txt` | From exported master, not rough cut |
| Captions sidecar | optional | Platform captions when not burned in |
| Thumbnail | optional | Truthful candidate path |
| Chapters | optional | `<rawDir>/edit/delivery/chapters.txt` |
| Thumbnails dir | optional | `<rawDir>/edit/delivery/thumbnails/` |
| End-screen checklist | optional | `<rawDir>/edit/review/end-screen-checklist.md` |
| Color QC | optional | `<rawDir>/edit/review/color-qc.md` |
| Sync check | optional | `<rawDir>/edit/review/sync-check.md` |
| Format diagnosis | optional | `<rawDir>/edit/review/format-diagnosis.md` |
| Framework selection | optional | `<rawDir>/edit/review/framework-selection.md` |
| Grade notes | optional | `<rawDir>/edit/review/grade-notes.md` |

---

## QC summary (AGENTS.md Master QC)

| Category | Result | Blocker notes |
| -------- | ------ | ------------- |
| Editorial | PASS / FAIL | promise, meaning, facts |
| Audio | PASS / FAIL | intelligibility, sync, loudness note |
| Visual | PASS / FAIL | margins, labels, readability |
| Captions | PASS / FAIL | final master match, names/terms |
| Rights / policy | PASS / FAIL | SOURCE-LOG, disclosure, AI |
| Technical | PASS / FAIL | resolution, fps, progressive, 48 kHz |

**Overall:** PASS / FAIL — do not label upload-ready on FAIL.

---

## Disclosure checklist

- [ ] Sponsorship / affiliate / gifted product disclosed
- [ ] AI-generated or meaningfully altered assets logged in SOURCE-LOG
- [ ] YouTube paid promotion settings reviewed
- [ ] Made-for-kids classification reviewed

---

## Shorts profile (when `profile: shorts`)

| Field | Value |
| ----- | ----- |
| Aspect | 9:16 |
| Duration (s) | |
| Max duration policy | 60s default; override in EDITLOG if approved |
| Safe margins | faces, captions, product details verified |
| Native vs extract | native \| from-master |

---

## Podcast-clip profile (when `profile: podcast-clip`)

| Field | Value |
| ----- | ----- |
| Aspect | 16:9 or 9:16 (document if reframed) |
| Duration (s) | |
| Segment source | from-master \| native |
| Rights audit | link to `edit/review/rights-audit.md` |
| Audio QC | link to `edit/review/audio-qc.md` |

---

## Trailer profile (when `profile: trailer`)

| Field | Value |
| ----- | ----- |
| Aspect | 16:9 typical |
| Target duration (s) | default 90 |
| Misleading preview check | PASS / FAIL |
| Rights audit | link to `edit/review/rights-audit.md` |
| Audio QC | link to `edit/review/audio-qc.md` |

---

## Open blockers

- 

---

## Approvals

| Gate | Reviewer | Date | Status |
| ---- | -------- | ---- | ------ |
| Master QC | | | |
| Upload ready | | | |
