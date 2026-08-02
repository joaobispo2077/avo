# Delivery manifest

**Version:** `YYYYMMDD-<slug>-master-v001`  
**Profile:** long-form | shorts | tiktok  
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

## Open blockers

- 

---

## Approvals

| Gate | Reviewer | Date | Status |
| ---- | -------- | ---- | ------ |
| Master QC | | | |
| Upload ready | | | |
